import json
import uuid
import httpx
from typing import Any, Dict, List, Optional
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

# ORM模型：Tool工具表，定义工具类型、来源类型枚举
from app.models.tool import Tool, ToolType, ToolSourceType
# RAG搜索服务客户端
from app.services.rag_service import rag_service_client
# API网关服务客户端，对接商店凭证、插件执行
from app.services.api_service import api_service_client
# MCP协议客户端库，streamable‑http传输会话
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from app.core.logging import get_logger

logger = get_logger(__name__)


class ToolExecutor:
    """Chat Completions API中动态工具执行器。
    根据tool_id注册工具，维护内存工具注册表，分发执行不同类型工具：
    RAG检索、MCP工具、商店工具(store)、插件(plugin)、HTTP webhook、function。
    """

    def __init__(self, db: AsyncSession, project_id: uuid.UUID):
        """
        :param db: SQLAlchemy异步数据库会话
        :param project_id: 当前所属项目ID，工具做项目隔离
        """
        self.db = db
        self.project_id = project_id
        # 内存工具注册表：key=工具名称，value={type, id, tool(ORM实例)}
        self._tool_registry: Dict[str, Dict[str, Any]] = {}
        # 插件执行上下文：访客id、会话id、agent id、语言
        self._context: Dict[str, Any] = {}

    def set_context(self, visitor_id: Optional[str] = None, session_id: Optional[str] = None, agent_id: Optional[str] = None, language: Optional[str] = None):
        """设置插件工具运行时上下文，会透传给插件服务。"""
        self._context = {
            "visitor_id": visitor_id,
            "session_id": session_id,
            "agent_id": agent_id,
            "language": language,
        }

    async def register_tools(
        self,
        tool_ids: Optional[List[uuid.UUID]] = None,
        collection_ids: Optional[List[str]] = None
    ):
        """注册工具，构建 tool_name → 执行元信息映射，存入内存 _tool_registry。
        - tool_ids：数据库Tool表记录id列表
        - collection_ids：RAG知识库集合id，虚拟rag_search_xxx工具
        注意：只做内存注册，不真正执行工具调用。
        """
        if tool_ids:
            # 查询本项目下、未删除的tool记录
            stmt = select(Tool).where(
                and_(
                    Tool.id.in_(tool_ids),
                    Tool.project_id == self.project_id,
                    Tool.deleted_at.is_(None),
                )
            )
            result = await self.db.execute(stmt)
            tools = result.scalars().all()
            for tool in tools:
                # 推导工具执行类型字符串，用于execute分发
                tool_type_str = "mcp" if tool.tool_type == ToolType.MCP else "function"
                if tool.tool_source_type == ToolSourceType.STORE:
                    tool_type_str = "store"
                elif tool.transport_type == "plugin":
                    tool_type_str = "plugin"
                elif tool.transport_type == "http_webhook":
                    tool_type_str = "http"

                self._tool_registry[tool.name] = {
                    "type": tool_type_str,
                    "id": str(tool.id),
                    "tool": tool
                }

        if collection_ids:
            # RAG知识库映射为虚拟工具，命名规则：rag_search_{collection_id前8位}
            for cid in collection_ids:
                short_id = cid.replace("-", "")[:8]
                tool_name = f"rag_search_{short_id}"
                self._tool_registry[tool_name] = {
                    "type": "rag",
                    "id": cid
                }

    async def execute(self, tool_name: str, arguments: Any) -> str:
        """根据工具名+参数执行工具，统一返回字符串；出错统一返回 <error>xxx</error> 格式，供LLM解析。
        :param tool_name: 注册表内工具名称
        :param arguments: 工具入参，可以是dict或者JSON字符串
        :return: 工具执行结果字符串
        """
        if tool_name not in self._tool_registry:
            return f"<error>Tool '{tool_name}' not found in registry</error>"

        info = self._tool_registry[tool_name]
        tool_type = info["type"]

        # 参数解析：如果传入是字符串，尝试json反序列化为字典
        args = arguments
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                return f"<error>Invalid JSON arguments for tool '{tool_name}'</error>"

        try:
            # 根据工具类型分发到不同私有执行函数
            if tool_type == "rag":
                return await self._execute_rag(info["id"], args)
            elif tool_type == "store":
                return await self._execute_store(info["tool"], args)
            elif tool_type == "mcp":
                return await self._execute_mcp(info["tool"], args)
            elif tool_type == "plugin":
                return await self._execute_plugin(info["tool"], args)
            elif tool_type == "http":
                return await self._execute_http(info["tool"], args)
            elif tool_type == "function":
                # 普通function类型暂无执行实现
                return f"<error>Tool '{tool_name}' is a generic function which is not yet implemented for direct execution</error>"
            else:
                return f"<error>Unsupported tool type: {tool_type}</error>"
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}", exc_info=True)
            return f"<error>{str(e)}</error>"

    async def _execute_rag(self, collection_id: str, args: Dict[str, Any]) -> str:
        """执行RAG向量检索虚拟工具，返回xml格式文档片段。"""
        query = args.get("query")
        if not query:
            return "<error>Missing 'query' argument for RAG search</error>"

        limit = args.get("limit", 10)
        try:
            results = await rag_service_client.search_documents(
                collection_id=collection_id,
                project_id=self.project_id,
                query=query,
                limit=limit
            )
        except Exception as e:
            return f"<error>RAG search failed: {str(e)}</error>"

        documents = results.get("results", [])
        if not documents:
            return "<documents />"

        # 包装为自定义xml格式，方便大模型解析
        serialized = [
            f'<document id="{doc.get("document_id", "unknown")}">{doc.get("content_preview", "")}</document>'
            for doc in documents
        ]
        return "<documents>" + "".join(serialized) + "</documents>"

    async def _execute_mcp(self, tool_model: Tool, args: Dict[str, Any]) -> str:
        """MCP协议工具执行，使用streamable‑http传输协议调用远端MCP服务。"""
        if not tool_model.endpoint:
            return "<error>MCP tool missing endpoint</error>"

        server_url = tool_model.endpoint.rstrip("/")
        # 自动补全/mcp路径后缀
        if not server_url.endswith("/mcp") and (tool_model.transport_type or "http") == "http":
            server_url += "/mcp"

        try:
            # streamablehttp_client：http流式双向会话
            async with streamablehttp_client(server_url) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_model.name, arguments=args)

                    # 提取MCP返回text类型content
                    if result.content:
                        texts = [c.text for c in result.content if hasattr(c, "text") and c.text]
                        if texts:
                            return "\n".join(texts)
                        return str(result.content)
                    return "Tool executed successfully with no content returned."
        except Exception as e:
            return f"<error>MCP execution failed: {str(e)}</error>"

    async def _execute_store(self, tool_model: Tool, args: Dict[str, Any]) -> str:
        """执行来自工具商店的工具；先获取项目绑定的商店api_key，代理请求商店执行接口。"""
        store_tool_id = tool_model.store_resource_id
        if not store_tool_id:
            return "<error>Store tool missing store_resource_id</error>"

        try:
            # 1. 获取项目绑定的商店凭证
            credential = await api_service_client.get_store_credential(str(self.project_id))
            if not credential or not credential.get("api_key"):
                return "<error>Project not bound to Store. Please bind credentials first.</error>"

            api_key = credential["api_key"]

            # 2. 请求商店执行API
            url = tool_model.endpoint
            if not url:
                return "<error>Store tool missing endpoint</error>"

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    url,
                    json={
                        "method": tool_model.name,
                        "params": args
                    },
                    headers={"X‑API‑Key": api_key}
                )

                # 402代表余额不足
                if response.status_code == 402:
                    return "<error>工具商店余额不足，请充值</error>"

                response.raise_for_status()

                result = response.json()
                # 商店返回MCP格式结果，提取text内容
                if isinstance(result, dict) and "content" in result:
                    content = result["content"]
                    if isinstance(content, list):
                        texts = [c.get("text") for c in content if isinstance(c, dict) and c.get("text")]
                        if texts:
                            return "\n".join(texts)
                    return str(content)
                return str(result)

        except Exception as e:
            logger.error(f"Store tool execution failed: {str(e)}", exc_info=True)
            return f"<error>Store execution failed: {str(e)}</error>"

    async def _execute_plugin(self, tool_model: Tool, args: Dict[str, Any]) -> str:
        """执行插件工具，调用api_service_client代理请求插件服务，透传上下文visitor_id/session_id等。"""
        plugin_id = tool_model.config.get("plugin_id")
        tool_name = tool_model.config.get("tool_name")

        if not plugin_id or not tool_name:
            return "<error>Plugin tool missing configuration (plugin_id or tool_name)</error>"

        try:
            result = await api_service_client.execute_plugin_tool(
                plugin_id=plugin_id,
                tool_name=tool_name,
                arguments=args,
                context=self._context,
            )

            if result.get("success"):
                return result.get("content", "工具执行成功")
            else:
                error_msg = result.get("error") or result.get("content") or "工具执行失败"
                return f"<error>{error_msg}</error>"
        except Exception as e:
            return f"<error>Plugin tool execution failed: {str(e)}</error>"

    async def _execute_http(self, tool_model: Tool, args: Dict[str, Any]) -> str:
        """执行自定义HTTP Webhook工具，支持GET/POST/PUT/DELETE/PATCH，读取config中的method、headers、timeout。"""
        if not tool_model.endpoint:
            return "<error>HTTP tool missing endpoint</error>"

        config = tool_model.config or {}
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {})
        timeout = config.get("timeout", 30.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method == "GET":
                    response = await client.get(tool_model.endpoint, params=args, headers=headers)
                elif method == "POST":
                    response = await client.post(tool_model.endpoint, json=args, headers=headers)
                elif method == "PUT":
                    response = await client.put(tool_model.endpoint, json=args, headers=headers)
                elif method == "DELETE":
                    response = await client.delete(tool_model.endpoint, params=args, headers=headers)
                elif method == "PATCH":
                    response = await client.patch(tool_model.endpoint, json=args, headers=headers)
                else:
                    return f"<error>Unsupported HTTP method: {method}</error>"

                response.raise_for_status()

                # 返回json字符串；非json直接返回原始文本
                try:
                    return json.dumps(response.json(), ensure_ascii=False)
                except ValueError:
                    return response.text
        except httpx.HTTPStatusError as e:
            return f"<error>HTTP execution failed with status {e.response.status_code}: {e.response.text}</error>"
        except Exception as e:
            return f"<error>HTTP execution failed: {str(e)}</error>"