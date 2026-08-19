"""工具运行时的辅助方法.

本模块提供多种工具的工厂函数与包装器，用于将外部能力（RAG检索、工作流、MCP协议、插件、通用HTTP接口）
统一封装为 Agno 框架可识别的 Function 工具对象，供 AI Agent 调用。
所有网络请求均采用异步实现，适配异步运行时环境。
"""

# 启用延迟注解求值，允许在类型注解中使用尚未定义的类（前向引用）
from __future__ import annotations

# 从内置模块导入 ExceptionGroup，用于批量异常的分组处理
from builtins import ExceptionGroup
# 导入 wraps 装饰器，用于保留被包装函数的元信息（函数名、文档字符串等）
from functools import wraps
# 导入类型注解工具
from typing import Any, Dict, List, Optional

# 异步 HTTP 客户端库，用于发起异步网络请求
import aiohttp
# JSON 序列化/反序列化工具
import json

# 导入 Agno 框架的 Function 类：用于封装 AI 可调用的工具函数
from agno.tools import Function
# 导入 MCP（Model Context Protocol）协议相关组件：客户端会话、协议错误类、工具定义
from mcp import ClientSession, McpError, Tool
# 导入 MCP 的流式 HTTP 客户端实现
from mcp.client.streamable_http import streamablehttp_client


async def create_rag_tool(
    rag_url: str,
    collection_id: str,
    project_id: Optional[str],
    filters: Optional[Dict[str, Any]] = None
) -> Function:
    """根据集合信息生成RAG查询工具.

    调用 RAG 服务接口获取集合元数据，动态生成一个可执行语义检索的工具函数，
    封装为 Agno Function 对象后返回，供大模型调用检索知识库。

    Args:
        rag_url: RAG 服务的基础 URL 地址
        collection_id: 目标文档集合的唯一 ID
        project_id: 所属项目 ID（必填，用于权限校验）
        filters: 可选的检索过滤条件字典，用于按元数据筛选文档

    Returns:
        封装好的 RAG 检索工具 Function 对象
    """
    # 项目 ID 为必填参数，为空直接抛出参数异常
    if not project_id:
        raise ValueError("project_id is required to create RAG tools")

    # 规范化 URL：去除末尾斜杠，避免拼接路径时出现双斜杠
    url = rag_url.rstrip("/")
    # 拼接「集合详情查询」接口路径
    collection_endpoint = f"{url}/v1/collections/{collection_id}"
    # 构造公共查询参数：项目 ID
    params = {"project_id": str(project_id)}

    # 异步发起 HTTP GET 请求，获取集合的元数据信息
    async with aiohttp.ClientSession() as session:
        async with session.get(collection_endpoint, params=params) as response:
            # 校验 HTTP 状态码，非 2xx 会抛出异常
            response.raise_for_status()
            # 解析响应 JSON 数据
            collection_data = await response.json()

    # 提取集合展示名称，为空则用集合 ID 兜底
    display_name = collection_data.get("display_name") or f"collection_{collection_id}"
    # 提取集合描述文本
    description = collection_data.get("description")

    # 构造工具的基础描述，说明工具的核心能力：语义检索
    tool_description = (
        f"Search documents within the '{display_name}' collection for results"
        " semantically similar to the query."
    )
    # 如果集合有自定义描述，追加到工具描述末尾，帮助大模型理解集合内容
    if description:
        tool_description = f"{tool_description} Collection description: {description}"

    # 构造符合规范的工具名称：仅包含字母、数字、下划线、点、横杠
    # 不再使用 display_name 作为工具名，避免特殊字符导致的兼容问题
    # 取集合 ID 去除横杠后的前 8 位作为短标识，保证唯一性且简洁
    short_id = (collection_id.replace("-", "")[:8]) if collection_id else "unknown"
    tool_name = f"rag_search_{short_id}".lower()

    # 定义内部异步函数：真正执行文档检索的逻辑
    async def search_collection(query: str) -> str:
        """对指定集合执行语义检索，返回格式化的文档结果字符串.

        Args:
            query: 自然语言查询语句

        Returns:
            XML 格式的文档列表字符串，便于大模型解析；无结果时返回空标签；出错返回错误标签
        """
        # 拼接「文档检索」接口路径
        search_endpoint = f"{url}/v1/collections/{collection_id}/documents/search"
        # 构造请求体：查询语句、返回条数（默认10条）、过滤条件
        payload = {"query": query, "limit": 10, "filters": filters}

        try:
            # 异步发起 POST 请求执行检索
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    search_endpoint,
                    params=params,
                    json=payload,
                ) as search_response:
                    search_response.raise_for_status()
                    data = await search_response.json()
        except Exception as exc:  # noqa: BLE001 - 捕获所有异常并格式化返回给大模型
            # 捕获所有异常，统一用 <error> 标签包裹错误信息返回
            return f"<error>{exc}</error>"

        # 提取检索结果列表
        documents = data.get("results", [])
        # 无结果时返回空文档标签
        if not documents:
            return "<documents />"

        # 将每条文档序列化为 XML 格式字符串，包含文档 ID 和内容
        serialized = [
            f'<document id="{doc.get("document_id", "unknown")}">{doc.get("content", doc.get("content_preview", ""))}</document>'
            for doc in documents
        ]
        # 拼接成完整的文档列表 XML 字符串并返回
        return "<documents>" + "".join(serialized) + "</documents>"

    # 将检索函数封装为 Agno Function 对象
    return Function(
        name=tool_name,          # 工具唯一名称
        description=tool_description,  # 工具功能描述（供大模型理解用途）
        parameters={             # 工具入参的 JSON Schema 定义
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query to search the collection.",
                }
            },
            "required": ["query"],  # 必填参数
        },
        entrypoint=search_collection,  # 工具执行的入口函数
        skip_entrypoint_processing=True,  # 跳过 Agno 对入口函数的自动参数解析，使用自定义 Schema
    )


async def create_workflow_tools(
    workflow_url: str,
    workflow_ids: List[str],
    project_id: Optional[str]
) -> List[Function]:
    """根据工作流信息批量生成工作流执行工具.

    批量查询工作流元数据，为每个工作流生成对应的执行工具，
    自动解析工作流输入参数并转换为 JSON Schema，供大模型按规范调用。

    Args:
        workflow_url: 工作流服务的基础 URL
        workflow_ids: 工作流 ID 列表
        project_id: 所属项目 ID（必填）

    Returns:
        工作流执行工具 Function 对象列表
    """
    # 校验项目 ID 必填
    if not project_id:
        raise ValueError("project_id is required to create workflow tools")

    # 工作流 ID 列表为空则直接返回空列表
    if not workflow_ids:
        return []

    # 规范化 URL
    url = workflow_url.rstrip("/")
    # 拼接「批量查询工作流」接口路径
    batch_endpoint = f"{url}/v1/workflows/batch"
    # 构造查询参数：项目 ID + 工作流 ID 列表
    params = {
        "project_id": str(project_id),
        "workflow_ids": workflow_ids
    }

    # 异步请求获取所有工作流的元数据
    async with aiohttp.ClientSession() as session:
        async with session.get(batch_endpoint, params=params) as response:
            response.raise_for_status()
            workflows_data = await response.json()

    tools = []
    # 遍历每个工作流，逐个生成工具
    for workflow_data in workflows_data:
        w_id = workflow_data.get("id")
        # 工作流名称，为空则用 ID 兜底
        name = workflow_data.get("name") or f"workflow_{w_id}"
        description = workflow_data.get("description")

        # 构造工具基础描述
        tool_description = f"Execute the '{name}' workflow."
        if description:
            tool_description = f"{tool_description} Workflow description: {description}"

        # 生成安全的工具名称：短 ID + 前缀
        short_id = (w_id.replace("-", "")[:8]) if w_id else "unknown"
        tool_name = f"workflow_{short_id}".lower()

        # 解析工作流的输入参数，转换为 JSON Schema 格式
        input_params = workflow_data.get("input_parameters") or []
        inputs_properties = {}  # 参数属性字典
        required_inputs = []    # 必填参数列表

        for param in input_params:
            p_name = param.get("name")
            p_type = param.get("type") or "string"
            p_desc = param.get("description") or ""

            # 工作流参数类型 -> JSON Schema 类型的映射
            js_type = p_type
            if js_type == "number":
                js_type = "number"  # JSON Schema 中 number 包含整数和浮点数

            # 构造单个参数的 Schema 定义
            inputs_properties[p_name] = {
                "type": js_type,
                "description": p_desc,
            }
            # 收集必填参数（默认必填）
            if param.get("required", True):
                required_inputs.append(p_name)

        # 构造完整的 inputs 参数 Schema
        inputs_schema = {
            "type": "object",
            "properties": inputs_properties,
            "description": "Input variables for the workflow.",
        }
        if required_inputs:
            inputs_schema["required"] = required_inputs

        # 使用闭包工厂生成执行函数：解决循环中异步函数的变量绑定问题
        # 确保每个执行函数绑定对应的工作流 ID，而非循环的最终值
        def make_execute_func(wf_id: str):
            async def execute_workflow(inputs: Optional[Dict[str, Any]] = None) -> str:
                """执行指定工作流，返回执行结果 JSON 字符串.

                Args:
                    inputs: 工作流输入参数字典

                Returns:
                    执行结果 JSON 字符串；出错返回错误标签
                """
                # 拼接工作流执行接口路径
                execute_endpoint = f"{url}/v1/workflows/{wf_id}/execute"
                exec_params = {"project_id": str(project_id)}
                # 请求体：输入参数、关闭流式、同步执行
                payload = {"inputs": inputs or {}, "stream": False, "async": False}

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            execute_endpoint,
                            params=exec_params,
                            json=payload,
                        ) as exec_response:
                            exec_response.raise_for_status()
                            data = await exec_response.json()
                            # 序列化为 JSON 字符串返回（保留中文）
                            return json.dumps(data, ensure_ascii=False)
                except Exception as exc:  # noqa: BLE001
                    return f"<error>{exc}</error>"
            return execute_workflow

        # 封装为 Function 对象并加入结果列表
        tools.append(
            Function(
                name=tool_name,
                description=tool_description,
                parameters={
                    "type": "object",
                    "properties": {
                        "inputs": inputs_schema
                    },
                    "required": ["inputs"] if required_inputs else [],
                },
                entrypoint=make_execute_func(w_id),
                skip_entrypoint_processing=True,
            )
        )

    return tools


def create_agno_mcp_tool(
    mcp_tool: Tool,
    mcp_server_url: str,
    headers: Optional[dict[str, str]] = None,
) -> Function:
    """为Agno生成基于MCP协议的工具包装.

    将符合 MCP（Model Context Protocol）协议的远程工具，封装为 Agno 可调用的 Function 对象。
    每次调用工具时都会建立新的 MCP 会话，执行完成后自动释放连接。

    Args:
        mcp_tool: MCP 协议定义的 Tool 对象，包含名称、描述、输入 Schema
        mcp_server_url: MCP 服务器的 HTTP 地址
        headers: 可选的 HTTP 请求头，用于鉴权等场景

    Returns:
        封装后的 Agno Function 工具对象
    """
    async def mcp_tool_entrypoint(**tool_args: Any) -> Any:
        """MCP 工具的实际执行入口.

        Args:
            **tool_args: 工具调用的关键字参数

        Returns:
            工具执行结果：优先返回文本内容，无文本则返回原始结果对象
        """
        # 建立 MCP 流式 HTTP 连接，获取读写流
        async with streamablehttp_client(mcp_server_url, headers=headers) as streams:
            read_stream, write_stream, _ = streams
            # 创建 MCP 客户端会话并初始化（完成协议握手）
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                # 调用远程 MCP 工具，传入参数
                result = await session.call_tool(mcp_tool.name, arguments=tool_args)
                # 优先提取第一条文本内容返回（适配大模型读取）
                if result.content and result.content[0].text:
                    return result.content[0].text
                # 无文本内容则返回完整结果对象
                return result

    # 封装为 Function 对象，直接复用 MCP 工具的名称、描述、输入 Schema
    return Function(
        name=mcp_tool.name,
        description=mcp_tool.description,
        parameters=mcp_tool.inputSchema,
        entrypoint=mcp_tool_entrypoint,
        skip_entrypoint_processing=True,
    )


def create_plugin_tool(
    plugin_id: str,
    tool_name: str,
    title: str,
    description: Optional[str],
    parameters: Optional[Dict[str, Any]],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Function:
    """根据插件信息生成插件工具包装.

    将平台插件系统中的工具封装为 Agno Function，通过内部 API 服务执行插件逻辑。

    Args:
        plugin_id: 插件唯一 ID
        tool_name: 插件内工具的名称
        title: 工具标题
        description: 工具描述
        parameters: 工具参数的 JSON Schema
        session_id: 当前会话 ID（上下文）
        user_id: 当前用户 ID（上下文）
        agent_id: 当前 Agent ID（上下文）

    Returns:
        封装后的插件工具 Function 对象
    """
    # 延迟导入：避免循环依赖，仅在执行时导入 API 服务客户端
    from app.services.api_service import api_service_client

    async def plugin_tool_entrypoint(**tool_args: Any) -> Any:
        """插件工具的实际执行入口.

        Args:
            **tool_args: 工具调用参数

        Returns:
            执行结果内容；失败返回错误标签
        """
        # 构造调用上下文：用户、会话、Agent 信息
        context = {
            "user_id": user_id,
            "session_id": session_id,
            "agent_id": agent_id,
        }
        try:
            # 调用 API 服务执行插件工具
            result = await api_service_client.execute_plugin_tool(
                plugin_id=plugin_id,
                tool_name=tool_name,
                arguments=tool_args,
                context=context,
            )
            # 执行成功返回内容，兜底文案为「工具执行成功」
            if result.get("success"):
                return result.get("content", "工具执行成功")
            else:
                # 执行失败，用 <error> 标签包裹错误信息
                return f"<error>{result.get('error', '工具执行失败')}</error>"
        except Exception as e:
            # 捕获执行异常，统一返回错误格式
            return f"<error>插件工具执行失败: {str(e)}</error>"

    # 封装为 Function 对象
    return Function(
        name=tool_name,
        description=description or title,  # 描述为空则用标题兜底
        parameters=parameters or {"type": "object", "properties": {}},  # 参数为空则用空对象兜底
        entrypoint=plugin_tool_entrypoint,
        skip_entrypoint_processing=True,
    )


def wrap_mcp_authenticate_tool(func: Function) -> Function:
    """捕获MCP鉴权异常并提示用户完成登录流程.

    装饰器工具：对 MCP 工具进行包装，专门捕获「需要用户交互/鉴权」的错误码，
    将原始协议错误转换为更友好的运行时异常，附带登录引导链接。

    Args:
        func: 原始 MCP 工具 Function 对象

    Returns:
        包装后的 Function 对象，具备鉴权错误处理能力
    """
    # 保存原始工具的入口函数
    original = func.entrypoint

    @wraps(original)
    async def wrapped(**kwargs: Any) -> Any:
        """包装后的执行函数：异常捕获与转换逻辑."""
        try:
            # 执行原始函数
            return await original(**kwargs)
        except BaseException as exc:  # noqa: BLE001
            # 从异常链中查找第一个 McpError 类型的异常
            mcp_error = _find_first_mcp_error(exc)
            # 未找到 MCP 错误则原样抛出异常
            if not mcp_error:
                raise

            # 提取错误详情对象
            error_details = getattr(mcp_error, "error", None)
            # 判断错误码：-32003 是 MCP 协议约定的「需要用户交互」错误码（通常为未登录/需授权）
            if error_details and getattr(error_details, "code", None) == -32003:
                # 提取错误数据字段
                data = getattr(error_details, "data", {}) or {}
                # 提取错误提示信息，兼容字符串和字典两种格式
                message = data.get("message") or "Interaction required"
                if isinstance(message, dict):
                    message = message.get("text") or "Interaction required"
                # 提取授权链接，有链接则拼接到提示信息中
                url = data.get("url")
                if url:
                    message = f"{message} {url}"
                # 抛出运行时异常，附带友好的鉴权提示
                raise RuntimeError(message) from exc
            # 其他 MCP 错误原样抛出
            raise

    # 从包装函数重新生成 Function 对象，保留原名称和描述
    return Function.from_callable(wrapped, name=func.name, description=func.description)


def create_http_tool(
    name: str,
    description: str,
    endpoint: str,
    method: str = "POST",
    headers: Optional[Dict[str, str]] = None,
    parameters: Optional[List[Dict[str, Any]]] = None,
    timeout: float = 30.0,
) -> Function:
    """根据HTTP接口信息生成工具包装.

    通用 HTTP 工具工厂：将任意 HTTP 接口封装为 Agno Function，
    支持常见 HTTP 方法，自动将参数转换为 JSON Schema，统一错误处理格式。

    Args:
        name: 工具名称
        description: 工具功能描述
        endpoint: HTTP 接口完整 URL
        method: HTTP 请求方法，默认 POST
        headers: 可选的请求头字典
        parameters: 接口参数定义列表（前端格式）
        timeout: 请求超时时间，默认 30 秒

    Returns:
        封装后的 HTTP 工具 Function 对象
    """
    async def http_tool_entrypoint(**tool_args: Any) -> Any:
        """HTTP 工具的实际执行入口.

        Args:
            **tool_args: 工具调用参数，会根据请求方法自动转为 query 参数或请求体

        Returns:
            接口响应内容（JSON 字符串或文本）；失败返回错误标签
        """
        # 延迟导入 httpx：按需加载，减少模块初始化依赖
        import httpx
        try:
            # 创建异步 HTTP 客户端并设置超时
            async with httpx.AsyncClient(timeout=timeout) as client:
                upper_method = method.upper()
                # 根据 HTTP 方法选择请求方式
                if upper_method == "GET":
                    # GET 请求：参数作为 query 字符串
                    response = await client.get(endpoint, params=tool_args, headers=headers)
                elif upper_method == "POST":
                    # POST 请求：参数作为 JSON 请求体
                    response = await client.post(endpoint, json=tool_args, headers=headers)
                elif upper_method == "PUT":
                    response = await client.put(endpoint, json=tool_args, headers=headers)
                elif upper_method == "DELETE":
                    response = await client.delete(endpoint, params=tool_args, headers=headers)
                elif upper_method == "PATCH":
                    response = await client.patch(endpoint, json=tool_args, headers=headers)
                else:
                    # 不支持的 HTTP 方法直接返回错误
                    return f"<error>Unsupported HTTP method: {method}</error>"

                # 校验 HTTP 状态码，非 2xx 抛出异常
                response.raise_for_status()
                try:
                    # 尝试解析为 JSON 并序列化返回（保留中文）
                    return json.dumps(response.json(), ensure_ascii=False)
                except ValueError:
                    # 响应非 JSON 格式则直接返回文本内容
                    return response.text
        except httpx.HTTPStatusError as e:
            # HTTP 状态码错误：返回状态码和响应体
            return f"<error>HTTP execution failed with status {e.response.status_code}: {e.response.text}</error>"
        except Exception as e:
            # 其他异常（网络错误、超时等）
            return f"<error>HTTP execution failed: {str(e)}</error>"

    # 将前端格式的参数列表转换为 JSON Schema 格式
    properties = {}
    required = []
    if parameters:
        for p in parameters:
            p_name = p.get("name")
            if not p_name:
                continue  # 跳过无名称的无效参数

            p_type = p.get("type", "string")
            # 前端类型 -> JSON Schema 类型映射
            js_type = p_type
            if p_type == "enum":
                js_type = "string"  # 枚举类型在 JSON Schema 中基础类型为 string

            # 构造单个参数的 Schema
            prop = {
                "type": js_type,
                "description": p.get("description", ""),
            }

            # 枚举类型补充可选值列表
            if p_type == "enum" and "enum_values" in p:
                prop["enum"] = p["enum_values"]

            properties[p_name] = prop
            # 收集必填参数
            if p.get("required"):
                required.append(p_name)

    # 封装为 Function 对象
    return Function(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": properties,
            "required": required,
        },
        entrypoint=http_tool_entrypoint,
        skip_entrypoint_processing=True,
    )


def _find_first_mcp_error(exc: BaseException) -> Optional[McpError]:
    """递归查找异常链中的第一个 McpError 对象.

    支持普通异常嵌套和 ExceptionGroup 异常组两种场景，
    用于从复杂异常结构中定位 MCP 协议错误。

    Args:
        exc: 根异常对象

    Returns:
        找到的第一个 McpError 对象；未找到返回 None
    """
    # 当前异常本身就是 McpError，直接返回
    if isinstance(exc, McpError):
        return exc
    # 当前异常是异常组，遍历组内所有子异常递归查找
    if isinstance(exc, ExceptionGroup):  # type: ignore[name-defined]
        for sub_exc in exc.exceptions:  # type: ignore[attr-defined]
            found = _find_first_mcp_error(sub_exc)
            if found:
                return found
    # 未找到返回 None
    return None