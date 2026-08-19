"""AI service client for proxying requests to external AI service."""
# 该模块：AI服务客户端，用于代理转发请求到后端外部AI服务(tgo‑ai)

import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
from uuid import uuid4, UUID

from datetime import date, datetime

import httpx
from fastapi import HTTPException

# 项目内部模块：配置、日志
from app.core.config import settings
from app.core.logging import get_logger

# 获取日志实例，日志分类标记为 ai_client
logger = get_logger("ai_client")


class AIServiceClient:
    """Client for communicating with the external AI service.
    与外部AI后端服务通信的异步HTTP客户端封装；
    封装统一请求、序列化、异常处理；对外提供Agent/Tool/Skill/Completion各类业务方法。
    """

    def __init__(self):
        """初始化客户端实例，从全局配置读取服务地址、超时、API密钥"""
        # rstrip("/") 避免拼接url出现双斜杠，如 http://xxx//api/v1
        self.base_url = str(settings.AI_SERVICE_URL).rstrip("/")
        self.timeout = settings.AI_SERVICE_TIMEOUT
        self.api_key = settings.AI_SERVICE_API_KEY

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for AI service requests (no auth required by downstream).
        获取请求公共请求头；根据最新接口规范，下游不再使用鉴权头部
        """
        headers = {
            "Content-Type": "application/json",
            "User‑Agent": "TGO‑API‑Service/0.1.0",
        }
        # Authentication headers have been removed per latest AI service API spec
        return headers

    def _to_jsonable(self, obj: Any) -> Any:
        """Recursively convert data to JSON‑serializable primitives (str/int/bool/list/dict).
        Handles UUID, datetime/date, sets, and Pydantic models (via model_dump if present).

        递归转换任意对象为JSON可序列化基础类型；
        处理：UUID、date/datetime、集合set、Pydantic v2模型；兜底转为字符串。
        """
        if obj is None:
            return None
        # 基础JSON原生类型直接返回
        if isinstance(obj, (str, int, float, bool)):
            return obj
        # UUID → 字符串
        if isinstance(obj, UUID):
            return str(obj)
        # 日期时间转ISO格式字符串，便于JSON传输
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        # 字典：key强制转字符串，value递归处理
        if isinstance(obj, dict):
            return {str(k): self._to_jsonable(v) for k, v in obj.items()}
        # list/tuple/set 统一转为list，内部元素递归序列化
        if isinstance(obj, (list, tuple, set)):
            return [self._to_jsonable(v) for v in obj]

        # Pydantic v2模型，不直接import pydantic，用hasattr做鸭子类型检测
        # model_dump(exclude_none=True)：剔除None字段，再递归序列化
        if hasattr(obj, "model_dump"):
            try:
                return self._to_jsonable(obj.model_dump(exclude_none=True))
            except Exception:
                pass

        # 兜底方案：利用json.dumps默认转换，失败则强制str()
        try:
            return json.loads(json.dumps(obj, default=str))
        except Exception:
            return str(obj)

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        content: Optional[str] = None,
    ) -> httpx.Response:
        """Make HTTP request to AI service.
        底层通用异步请求方法：封装httpx.AsyncClient，日志埋点，超时/网络异常捕获
        返回原始httpx.Response对象，不做业务解析；解析交给 _handle_response。

        :param method: HTTP方法 GET/POST/PATCH/DELETE
        :param endpoint: 请求路径，如 /api/v1/agents
        :param json_data: 需要POST/PATCH的JSON payload字典
        :param params: URL查询参数
        :param extra_headers: 额外追加的请求头，会合并公共头
        :param content: 原始字符串body（非json，用于上传文本文件等场景）
        :return: httpx.Response 原始响应对象
        """
        url = f"{self.base_url}{endpoint}"
        # 生成链路追踪ID，打在请求头X‑Request‑ID，日志也带上，方便排查全链路日志
        request_id = str(uuid4())

        headers = self._get_headers()
        headers["X‑Request‑ID"] = request_id
        if extra_headers:
            headers.update(extra_headers)

        # 打印请求日志，extra附加结构化字段便于日志系统检索
        logger.info(
            f"AI service request: {method} {url}",
            extra={
                "request_id": request_id,
                "method": method,
                "url": url,
                "params": params,
            }
        )

        try:
            # 异步httpx客户端，上下文管理器自动关闭连接
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                kwargs: Dict[str, Any] = {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "params": params,
                }
                # json_data不为None，先调用_to_jsonable处理不可序列化对象再传入httpx
                if json_data is not None:
                    kwargs["json"] = self._to_jsonable(json_data)
                # content用于原始文本body，与json互斥
                if content is not None:
                    kwargs["content"] = content
                response = await client.request(**kwargs)

                # 打印响应日志：状态码、耗时
                logger.info(
                    f"AI service response: {response.status_code}",
                    extra={
                        "request_id": request_id,
                        "status_code": response.status_code,
                        "response_time": response.elapsed.total_seconds() if response.elapsed else None,
                    }
                )
                return response

        except httpx.TimeoutException as e:
            # 请求超时：记录error日志，抛出FastAPI 504网关超时异常
            logger.error(
                f"AI service timeout: {url}",
                extra={"request_id": request_id, "timeout": self.timeout}
            )
            raise HTTPException(
                status_code=504,
                detail="AI service request timed out"
            )
        except httpx.RequestError as e:
            # 网络层面异常：连接失败、DNS错误等，抛出502网关错误
            logger.error(
                f"AI service request error: {e}",
                extra={"request_id": request_id, "error": str(e)}
            )
            raise HTTPException(
                status_code=502,
                detail="Failed to connect to AI service"
            )

    async def _handle_response(self, response: httpx.Response) -> Any:
        """Handle AI service response and convert errors.
        处理原始Response：成功返回解析后数据；非2xx状态码统一包装为FastAPI HTTPException抛出

        - 204 No Content 返回 None
        - 正常响应优先解析json，解析失败返回原始文本
        - 错误响应：尝试读取后端返回的error结构体，日志告警，向上抛出HTTPException
        """
        if response.is_success:
            # 204无内容直接返回None
            if response.status_code == 204:
                return None
            try:
                return response.json()
            except json.JSONDecodeError:
                # 返回不是合法JSON，返回原始文本
                return response.text

        # -------- 处理错误响应 --------
        try:
            error_data = response.json()
        except json.JSONDecodeError:
            # 错误返回不是JSON，包装错误消息
            error_data = {"error": {"message": response.text or "Unknown error"}}

        logger.warning(
            f"AI service error response: {response.status_code}",
            extra={
                "status_code": response.status_code,
                "error_data": error_data,
            }
        )
        # 将下游AI服务的http状态码透传给上层接口
        raise HTTPException(
            status_code=response.status_code,
            detail=error_data
        )

    # ================= Agent endpoints 代理Agent相关接口 =================
    async def run_supervisor_agent(
        self,
        message: str,
        project_id: str,
        *,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream: bool = False,
        mcp_url: Optional[str] = None,
        rag_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run supervisor agent workflow and return response content.
        调用Supervisor智能体执行工作流，非流式调用；
        :param message: 用户输入prompt
        :param project_id: 项目ID放在URL query参数
        :param agent_id: 指定agent实例
        :param session_id: 会话ID，用于记忆上下文
        :param user_id: 用户标识
        :param stream: 是否流式，此方法为非流式，传False
        :param mcp_url: MCP服务地址
        :param rag_url: RAG知识库服务地址
        :return: AI返回字典；如果返回不是dict则包装成{"content":xxx}
        """
        payload: Dict[str, Any] = {
            "message": message,
            "stream": stream,
        }
        # 可选字段不为None才加入payload，避免传null给下游
        if agent_id:
            payload["agent_id"] = agent_id
        if session_id:
            payload["session_id"] = session_id
        if user_id:
            payload["user_id"] = user_id
        if mcp_url:
            payload["mcp_url"] = mcp_url
        if rag_url:
            payload["rag_url"] = rag_url

        response = await self._make_request(
            "POST",
            "/api/v1/agents/run",
            json_data=payload,
            params={"project_id": project_id},
        )
        data = await self._handle_response(response)
        if isinstance(data, dict):
            return data
        # 如果返回是字符串文本，包装为content字段返回
        return {"content": data}

    async def run_supervisor_agent_stream(
        self,
        message: str,
        project_id: str,
        *,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        mcp_url: Optional[str] = None,
        rag_url: Optional[str] = None,
        enable_memory: Optional[bool] = None,
        system_message: Optional[str] = None,
        expected_output: Optional[str] = None,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        """Stream supervisor agent events as they arrive.
        Supervisor Agent**SSE流式接口**；不使用_make_request，自己手动调用httpx.stream。
        返回异步生成器，每次yield (event_name, parsed_data)。
        SSE协议格式：event:xxx \n data:{...}，空行代表事件结束。

        注意：stream模式设置timeout=None，因为长连接流不能设置固定超时。
        """
        payload: Dict[str, Any] = {
            "message": message,
            "stream": True,
        }
        if agent_id:
            payload["agent_id"] = agent_id
        if session_id:
            payload["session_id"] = session_id
        if user_id:
            payload["user_id"] = user_id
        if mcp_url:
            payload["mcp_url"] = mcp_url
        if rag_url:
            payload["rag_url"] = rag_url
        if enable_memory is not None:
            payload["enable_memory"] = enable_memory
        if system_message is not None:
            payload["system_message"] = system_message
        if expected_output is not None:
            payload["expected_output"] = expected_output

        url = f"{self.base_url}/api/v1/agents/run"
        request_id = str(uuid4())
        headers = self._get_headers()
        headers["X‑Request‑ID"] = request_id
        # SSE流需要 Accept: text/event‑stream
        headers.setdefault("Accept", "text/event‑stream")

        logger.info(
            "AI service stream request: POST %s",
            url,
            extra={"request_id": request_id},
        )

        try:
            # 流式长连接 timeout=None，禁止总超时
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=self._to_jsonable(payload),
                    params={"project_id": project_id},
                ) as response:
                    # 非200状态码，读取错误信息抛异常
                    if response.status_code != 200:
                        try:
                            error_data = await response.json()
                        except Exception:
                            error_body = await response.aread()
                            error_data = {"error": error_body.decode("utf‑8", errors="ignore")}
                        logger.warning(
                            "AI service stream error: %s",
                            response.status_code,
                            extra={"request_id": request_id, "detail": error_data},
                        )
                        raise HTTPException(status_code=response.status_code, detail=error_data)

                    event_name: Optional[str] = None
                    data_lines: List[str] = []

                    # 按行迭代SSE响应流 aiter_lines()
                    async for line in response.aiter_lines():
                        if not line:
                            # 空行：代表一个SSE事件结束，解析已收集data_lines
                            if not data_lines:
                                event_name = None
                                continue
                            data_text = '\n'.join(data_lines)
                            try:
                                parsed = json.loads(data_text)
                            except json.JSONDecodeError:
                                parsed = data_text
                            yield (event_name or "message", parsed)
                            # 重置状态，准备接收下一个事件
                            event_name = None
                            data_lines = []
                            continue
                        # SSE注释行以冒号开头，直接跳过
                        if line.startswith(":"):
                            continue
                        # event: xxx → 解析事件名
                        if line.startswith("event:"):
                            event_name = line.split(":", 1)[1].strip()
                        # data: xxx → 收集data行，支持多行data
                        elif line.startswith("data:"):
                            data_lines.append(line.split(":", 1)[1].strip())

                    # 流结束，处理缓冲区残留未输出的数据
                    if data_lines:
                        data_text = '\n'.join(data_lines)
                        try:
                            parsed = json.loads(data_text)
                        except json.JSONDecodeError:
                            parsed = data_text
                        yield (event_name or "message", parsed)

        except httpx.TimeoutException:
            logger.error("AI service stream timeout: %s", url, extra={"request_id": request_id})
            raise HTTPException(status_code=504, detail="AI service stream timed out")
        except httpx.RequestError as exc:
            logger.error("AI service stream request error: %s", exc, extra={"request_id": request_id})
            raise HTTPException(status_code=502, detail="Failed to connect to AI service")

    async def cancel_supervisor_run(
        self,
        project_id: str,
        run_id: str,
        reason: Optional[str] = None,
    ) -> Any:
        """Cancel a running supervisor execution by run_id.
        Proxies to AI service: POST /api/v1/agents/run/{run_id}/cancel
        取消正在运行的agent任务；可附带取消原因
        """
        body = {"reason": reason} if reason else None
        response = await self._make_request(
            "POST",
            f"/api/v1/agents/run/{run_id}/cancel",
            json_data=body,
            params={"project_id": project_id},
        )
        return await self._handle_response(response)

    async def check_agents_exist(
        self,
        project_id: str,
    ) -> bool:
        """
        Check if any agents exist for the specified project.

        Args:
            project_id: Project ID to check

        Returns:
            True if agents exist, False otherwise

        检查项目下是否存在Agent；
        注意：接口调用失败时，为避免业务阻塞，保守返回True（假定存在agent）
        """
        try:
            response = await self._make_request(
                "GET",
                "/api/v1/agents/exists",
                params={"project_id": project_id},
            )
            data = await self._handle_response(response)
            if isinstance(data, dict):
                return data.get("exists", False)
            return False
        except HTTPException:
            # 接口报错，保守策略：假设agent存在，不阻断上层业务
            logger.warning(
                f"Failed to check agents existence for project {project_id}, assuming agents exist"
            )
            return True
        except Exception as e:
            logger.warning(
                f"Unexpected error checking agents existence: {e}, assuming agents exist"
            )
            return True

    async def list_agents(
        self,
        project_id: str,
        model: Optional[str] = None,
        is_default: Optional[bool] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """List agents from AI service.
        分页查询项目下agent列表；支持model、is_default过滤
        """
        params = {"limit": limit, "offset": offset, "project_id": project_id}
        if model:
            params["model"] = model
        if is_default is not None:
            params["is_default"] = is_default

        response = await self._make_request(
            "GET", "/api/v1/agents", params=params
        )
        return await self._handle_response(response)

    async def create_agent(
        self,
        project_id: str,
        agent_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create agent in AI service. 创建Agent"""
        response = await self._make_request(
            "POST", "/api/v1/agents", json_data=agent_data, params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def get_agent(
        self,
        project_id: str,
        agent_id: str,
        include_tools: bool = True,
        include_collections: bool = False,
        include_workflows: bool = False,
    ) -> Dict[str, Any]:
        """Get agent from AI service.
        获取Agent详情；可选是否附带绑定工具、知识库集合、工作流信息
        """
        params = {
            "include_tools": include_tools,
            "include_collections": include_collections,
            "include_workflows": include_workflows,
            "project_id": project_id,
        }
        response = await self._make_request(
            "GET", f"/api/v1/agents/{agent_id}", params=params
        )
        return await self._handle_response(response)

    async def update_agent(
        self,
        project_id: str,
        agent_id: str,
        agent_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update agent in AI service. PATCH更新Agent基础信息"""
        response = await self._make_request(
            "PATCH", f"/api/v1/agents/{agent_id}", json_data=agent_data, params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def delete_agent(
        self,
        project_id: str,
        agent_id: str,
    ) -> None:
        """Delete agent from AI service. 删除Agent"""
        response = await self._make_request(
            "DELETE", f"/api/v1/agents/{agent_id}", params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def set_agent_tool_enabled(
        self,
        project_id: str,
        agent_id: str,
        tool_id: str,
        enabled: bool,
    ) -> None:
        """Enable or disable a specific tool binding for an agent.
        设置Agent是否启用某个绑定的工具；下游返回204 No‑Content
        """
        response = await self._make_request(
            "PATCH",
            f"/api/v1/agents/{agent_id}/tools/{tool_id}/enabled",
            json_data={"enabled": enabled},
            params={"project_id": project_id}
        )
        # 204无内容直接返回None，否则解析响应
        if response.status_code == 204:
            return None
        return await self._handle_response(response)

    async def set_agent_collection_enabled(
        self,
        project_id: str,
        agent_id: str,
        collection_id: str,
        enabled: bool,
    ) -> None:
        """Enable or disable a specific collection binding for an agent.
        设置Agent是否启用某个知识库集合绑定
        """
        response = await self._make_request(
            "PATCH",
            f"/api/v1/agents/{agent_id}/collections/{collection_id}/enabled",
            json_data={"enabled": enabled},
            params={"project_id": project_id}
        )
        if response.status_code == 204:
            return None
        return await self._handle_response(response)

    async def set_agent_workflow_enabled(
        self,
        project_id: str,
        agent_id: str,
        workflow_id: str,
        enabled: bool,
    ) -> None:
        """Enable or disable a specific workflow binding for an agent.
        设置Agent是否启用绑定的工作流
        """
        response = await self._make_request(
            "PATCH",
            f"/api/v1/agents/{agent_id}/workflows/{workflow_id}/enabled",
            json_data={"enabled": enabled},
            params={"project_id": project_id}
        )
        if response.status_code == 204:
            return None
        return await self._handle_response(response)

    async def clear_session_memory(
        self,
        project_id: str,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Clear memory for a session in the AI service.
        清空指定会话的记忆存储
        """
        response = await self._make_request(
            "DELETE",
            f"/api/v1/agents/sessions/{session_id}/memory",
            params={"project_id": project_id, "user_id": user_id},
        )
        return await self._handle_response(response)

    # ================= Tools endpoints 工具管理接口 =================
    async def list_tools(
        self,
        project_id: str,
        tool_type: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        """List tools from AI service. 查询项目工具列表；可包含已软删除工具"""
        params = {"project_id": project_id, "include_deleted": include_deleted}
        if tool_type:
            params["tool_type"] = tool_type

        response = await self._make_request(
            "GET", "/api/v1/tools", params=params
        )
        return await self._handle_response(response)

    async def create_tool(
        self,
        tool_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create tool in AI service. 创建工具"""
        response = await self._make_request(
            "POST", "/api/v1/tools", json_data=tool_data
        )
        return await self._handle_response(response)

    async def update_tool(
        self,
        project_id: str,
        tool_id: str,
        tool_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update tool in AI service. 更新工具"""
        response = await self._make_request(
            "PATCH",
            f"/api/v1/tools/{tool_id}",
            json_data=tool_data,
            params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def delete_tool(
        self,
        project_id: str,
        tool_id: str,
    ) -> Dict[str, Any]:
        """Delete tool from AI service (soft delete). 软删除工具"""
        response = await self._make_request(
            "DELETE", f"/api/v1/tools/{tool_id}", params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def create_or_update_tool(
        self,
        project_id: str,
        tool_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create or update a tool in the AI service.
        幂等：按工具名存在则更新，不存在则新建；
        先list_tools遍历查找同名工具
        """
        tool_name = tool_data.get("name")
        # 查询全部工具，查找同名
        existing_tools = await self.list_tools(project_id)
        existing_tool = next((t for t in existing_tools if t["name"] == tool_name), None)

        if existing_tool:
            # 找到已存在，执行更新
            return await self.update_tool(project_id, existing_tool["id"], tool_data)
        else:
            # 不存在，创建；补充project_id进payload
            data = {**tool_data, "project_id": project_id}
            return await self.create_tool(data)

    async def delete_tools_by_prefix(
        self,
        project_id: str,
        prefix: str,
    ) -> None:
        """Delete all tools with names starting with prefix.
        批量删除名字以prefix为前缀的全部工具；循环逐个调用delete_tool
        """
        tools = await self.list_tools(project_id)
        for tool in tools:
            if tool["name"].startswith(prefix):
                await self.delete_tool(project_id, tool["id"])

    # ================= Chat completions 兼容OpenAI格式对话补全 =================
    async def chat_completions(
        self,
        project_id: str,
        provider_id: str,
        model: str,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a chat completion using the AI service.

        This proxies to the AI service's /api/v1/chat/completions endpoint,
        which is compatible with OpenAI's Chat Completions API format.

        Args:
            project_id: Project ID for authorization
            provider_id: UUID of the LLM provider to use
            model: Model identifier (e.g., 'gpt‑4', 'claude‑3‑opus')
            messages: List of conversation messages with 'role' and 'content'
            temperature: Sampling temperature (0‑2)
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response (not supported yet)

        Returns:
            Chat completion response with choices
        """
        payload: Dict[str, Any] = {
            "provider_id": provider_id,
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        response = await self._make_request(
            "POST",
            "/api/v1/chat/completions",
            json_data=payload,
            params={"project_id": project_id},
        )
        return await self._handle_response(response)

    # ------------------------------------------------------------------
    # Skill management (proxy to tgo‑ai /api/v1/skills)
    # Skill技能模块代理接口
    # ------------------------------------------------------------------

    def _skill_headers(self, project_id: str) -> Dict[str, str]:
        """Build extra headers for skill requests. skill接口需要X‑Project‑Id请求头传递项目ID"""
        return {"X‑Project‑Id": project_id}

    async def import_skill(self, project_id: str, import_data: Dict[str, Any]) -> Dict[str, Any]:
        """Import a skill from GitHub (proxy to tgo‑ai). 从GitHub导入技能"""
        response = await self._make_request(
            "POST",
            "/api/v1/skills/import",
            json_data=import_data,
            extra_headers=self._skill_headers(project_id),
        )
        return await self._handle_response(response)

    async def list_skills(self, project_id: str) -> List[Dict[str, Any]]:
        """List all skills visible to a project (private + official). 查询项目可见全部技能(私有+官方)"""
        response = await self._make_request(
            "GET",
            "/api/v1/skills",
            extra_headers=self._skill_headers(project_id),
        )
        return await self._handle_response(response)

    async def create_skill(self, project_id: str, skill_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new project‑private skill. 创建项目私有技能"""
        response = await self._make_request(
            "POST",
            "/api/v1/skills",
            json_data=skill_data,
            extra_headers=self._skill_headers(project_id),
        )
        return await self._handle_response(response)

    async def get_skill(self, project_id: str, skill_name: str) -> Dict[str, Any]:
        """Get skill details. 获取技能详情"""
        response = await self._make_request(
            "GET",
            f"/api/v1/skills/{skill_name}",
            extra_headers=self._skill_headers(project_id),
        )
        return await self._handle_response(response)

    async def update_skill(
        self, project_id: str, skill_name: str, skill_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update a project‑private skill. 更新私有技能"""
        response = await self._make_request(
            "PATCH",
            f"/api/v1/skills/{skill_name}",
            json_data=skill_data,
            extra_headers=self._skill_headers(project_id),
        )
        return await self._handle_response(response)

    async def toggle_skill(
        self, project_id: str, skill_name: str, toggle_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Toggle a skill's enabled/disabled state. 切换技能启用禁用状态"""
        response = await self._make_request(
            "PUT",
            f"/api/v1/skills/{skill_name}/toggle",
            json_data=toggle_data,
            extra_headers=self._skill_headers(project_id),
        )
        return await self._handle_response(response)

    async def delete_skill(self, project_id: str, skill_name: str) -> None:
        """Delete a project‑private skill. 删除私有技能"""
        response = await self._make_request(
            "DELETE",
            f"/api/v1/skills/{skill_name}",
            extra_headers=self._skill_headers(project_id),
        )
        # 200/204视为成功，否则抛异常
        if response.status_code not in (200, 204):
            await self._handle_response(response)

    async def get_skill_file(
        self, project_id: str, skill_name: str, file_path: str
    ) -> str:
        """Read a sub‑file from a skill. 读取技能内部子文件文本内容"""
        response = await self._make_request(
            "GET",
            f"/api/v1/skills/{skill_name}/files/{file_path}",
            extra_headers=self._skill_headers(project_id),
        )
        if response.status_code != 200:
            await self._handle_response(response)
        return response.text

    async def put_skill_file(
        self,
        project_id: str,
        skill_name: str,
        file_path: str,
        file_content: str,
    ) -> None:
        """Create or update a sub‑file inside a skill. 创建/覆盖技能内部子文件；Content‑Type:text/plain"""
        headers = self._skill_headers(project_id)
        headers["Content‑Type"] = "text/plain; charset=utf‑8"
        response = await self._make_request(
            "PUT",
            f"/api/v1/skills/{skill_name}/files/{file_path}",
            content=file_content,
            extra_headers=headers,
        )
        if response.status_code not in (200, 201):
            await self._handle_response(response)

    async def delete_skill_file(
        self, project_id: str, skill_name: str, file_path: str
    ) -> None:
        """Delete a sub‑file from a skill. 删除技能内子文件"""
        response = await self._make_request(
            "DELETE",
            f"/api/v1/skills/{skill_name}/files/{file_path}",
            extra_headers=self._skill_headers(project_id),
        )
        if response.status_code not in (200, 204):
            await self._handle_response(response)


# 全局单例客户端实例，业务层直接导入 ai_client 使用
ai_client = AIServiceClient()