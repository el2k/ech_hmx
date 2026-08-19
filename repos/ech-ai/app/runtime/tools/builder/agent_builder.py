"""Agent builder with RAG and MCP integration."""
# 支持RAG、MCP、插件、工作流、记忆、技能系统的Agent底层构建器

from __future__ import annotations

import asyncio
import json
import time
import traceback
import types
import uuid
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

import httpx
from agno.agent import Agent, RemoteAgent
from agno.db.postgres import PostgresDb
from agno.memory import MemoryManager
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput, RunOutputEvent
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.tools.mcp import MCPTools, MultiMCPTools
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.config import settings
from app.core.logging import get_logger
from app.models.internal import Agent as InternalAgent
from app.models.internal import AgentTool
from app.models.tool import Tool as ToolModel
from app.runtime.core.exceptions import (
    InvalidConfigurationError,
    MCPAuthenticationError,
    MCPConnectionError,
    MCPToolError,
    MissingConfigurationError,
)
from app.runtime.tools.config import ToolsRuntimeSettings
from app.runtime.tools.models import (
    AgentConfig,
    AgentRunRequest,
    MCPConfig,
    RagConfig,
    WorkflowConfig,
)
from app.runtime.tools.token import get_mcp_access_token
from app.runtime.tools.utils import (
    create_agno_mcp_tool,
    create_http_tool,
    create_plugin_tool,
    create_rag_tool,
    create_workflow_tools,
    wrap_mcp_authenticate_tool,
)
from app.services.api_service import api_service_client
from app.json_render import JsonRenderSchemaManager

_logger = get_logger(__name__)


class StoreRemoteAgent(RemoteAgent):
    """
    Custom RemoteAgent that allows overriding id and name for direct agent runs.
    自定义扩展RemoteAgent：原生RemoteAgent所有工具必须在远端服务执行；本类实现**大模型推理远端跑，工具在本地服务执行**
    支持本地工具绑定：
    - tools: 与本地 Agent 一致的工具属性
    - 内部透明执行：arun 内部自动处理工具执行循环，对调用者无感知
    """

    def __init__(self, *args, **kwargs):
        # 自定义覆盖字段，覆盖远端随机生成的agent id/name/metadata，对齐数据库记录
        self._override_id = kwargs.pop("override_id", None)
        self._override_name = kwargs.pop("override_name", None)
        self._override_metadata = kwargs.pop("override_metadata", None)
        self._api_key = kwargs.pop("api_key", None)
        self.knowledge_filters = kwargs.pop("knowledge_filters", None)

        # 本地工具集合，不和父类tools冲突，父类tools用于远端服务
        self.local_tools: List[Union[Function, Callable]] = kwargs.pop("tools", [])
        self._tool_map: Dict[str, Function] = {}
        # 构建工具名字 -> 工具对象映射字典，方便后续快速查找执行
        self._build_tool_map()

        super().__init__(*args, **kwargs)

    def _build_tool_map(self) -> None:
        """构建工具名称到工具对象的映射，支持 Toolkit 和普通 Function"""
        self._tool_map = {}
        for tool in self.local_tools:
            if isinstance(tool, Function):
                self._tool_map[tool.name] = tool
            elif isinstance(tool, Toolkit):
                # MCPTools属于Toolkit，取出内部全部异步工具
                toolkit_tools = tool.get_async_functions()
                for name, func in toolkit_tools.items():
                    self._tool_map[name] = func
            elif callable(tool):
                # 普通可调用函数
                name = getattr(tool, "__name__", str(tool))
                self._tool_map[name] = tool
        _logger.debug(f"Built tool map with {len(self._tool_map)} tools: {list(self._tool_map.keys())}")

    def _build_tools_schema(self) -> List[Dict[str, Any]]:
        """将本地工具转换为 JSON Schema 格式，发送给远程 Agent
        远端大模型拿到schema，才知道可以调用哪些工具、参数是什么
        """
        schemas = []
        for tool in self.local_tools:
            if isinstance(tool, Function):
                schemas.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.parameters or {"type": "object", "properties": {}},
                })
            elif callable(tool):
                name = getattr(tool, "__name__", str(tool))
                doc = getattr(tool, "__doc__", "") or ""
                schemas.append({
                    "name": name,
                    "description": doc,
                    "parameters": {"type": "object", "properties": {}},
                })
        return schemas

    def _has_pending_tool_calls(self, result: Any) -> bool:
        """检查结果中是否有需要外部执行的工具调用
        远端返回标记 external_execution_required=True，代表工具不能远端执行，交给本地执行
        """
        _logger.debug(f"Checking for pending tool calls in: {type(result)}")

        tools = []
        if isinstance(result, dict):
            tools = result.get('tools', [])
        elif hasattr(result, 'tools'):
            tools = result.tools or []

        if not tools:
            _logger.debug("No tools attribute or empty tools list")
            return False

        for tool_exec in tools:
            if isinstance(tool_exec, dict):
                is_ext = tool_exec.get('external_execution_required', False)
                tool_name = tool_exec.get('tool_name', 'unknown')
            else:
                is_ext = hasattr(tool_exec, 'external_execution_required') and tool_exec.external_execution_required
                tool_name = getattr(tool_exec, 'tool_name', 'unknown')

            _logger.debug(f"Tool {tool_name}: external_execution_required={is_ext}")
            if is_ext:
                print(f"has_pending_tool_calls--> True (tool: {tool_name})")
                return True
        return False

    async def _execute_tools_locally(self, tool_calls: List[Union[ToolExecution, Dict[str, Any]]]) -> List[ToolExecution]:
        """
        本地执行工具，与本地 Agent 行为一致。
        执行后填充结果并清除 external_execution_required 标志。
        返回处理完成的tool对象，回传给远端agent做continue_run继续推理
        """
        updated_tool_calls: List[ToolExecution] = []

        print("_execute_tools_locally--->", tool_calls)

        for tc_raw in tool_calls:
            # 统一转为ToolExecution对象
            if isinstance(tc_raw, dict):
                tc = ToolExecution(**tc_raw)
            else:
                tc = tc_raw

            # 已经处理完毕的工具直接跳过，防止重复提交给远端造成400错误
            if not (hasattr(tc, 'external_execution_required') and tc.external_execution_required):
                _logger.debug(f"Skipping already processed tool: {getattr(tc, 'tool_name', 'unknown')}")
                continue

            tool_name = tc.tool_name
            tool_args = tc.tool_args or {}

            _logger.debug(f"Executing local tool: {tool_name} with args: {tool_args}")

            tool = self._tool_map.get(tool_name)
            if not tool:
                _logger.warning(f"Tool {tool_name} not found in local tools")
                tc.result = f"Error: Tool '{tool_name}' not found"
                tc.external_execution_required = False
                updated_tool_calls.append(tc)
                continue
            print("tool--->", tool)
            try:
                # 区分Function对象 / 普通函数，同步/异步执行
                if isinstance(tool, Function):
                    if tool.entrypoint:
                        if asyncio.iscoroutinefunction(tool.entrypoint):
                            result = await tool.entrypoint(**tool_args)
                        else:
                            result = tool.entrypoint(**tool_args)
                    else:
                        result = f"Tool {tool_name} has no entrypoint"
                elif callable(tool):
                    if asyncio.iscoroutinefunction(tool):
                        result = await tool(**tool_args)
                    else:
                        result = tool(**tool_args)
                else:
                    result = f"Tool {tool_name} is not callable"
                print("tool-result--->", result)
                # 结果统一转字符串，保证序列化兼容
                if not isinstance(result, str):
                    try:
                        result = json.dumps(result, ensure_ascii=False, default=str)
                    except Exception:
                        result = str(result)

                tc.result = result
                _logger.debug(f"Tool {tool_name} executed successfully: {result[:100]}...")

            except Exception as e:
                error_detail = traceback.format_exc()
                _logger.error(f"Error executing tool {tool_name}: {e}\n{error_detail}")

                error_msg = f"Error executing tool: {str(e)}"
                try:
                    if hasattr(e, 'exceptions'):
                        sub_errors = [f"{type(ex).__name__}: {str(ex)}" for ex in e.exceptions]
                        error_msg += f" (Sub‑errors: {', '.join(sub_errors)})"
                except Exception:
                    pass

                tc.result = error_msg

            # 标记工具已经本地执行完成
            tc.external_execution_required = False
            updated_tool_calls.append(tc)

        return updated_tool_calls

    @property
    def id(self) -> str:
        """覆盖id属性，优先使用数据库的agent_id，不用远端随机id"""
        return self._override_id or self.agent_id

    @property
    def agentos_client(self):
        """Override to ensure headers are injected into the client.
        重写客户端属性，自动注入鉴权请求头 X‑API‑Key / Bearer token，访问远端store服务
        """
        client = getattr(self, "_store_agentos_client", None)
        if client is None:
            return None

        api_key = self._api_key
        if not api_key:
            api_key = settings.store_api_key

        if api_key:
            if hasattr(client, "headers"):
                if client.headers is None:
                    client.headers = {}
                client.headers["X‑API‑Key"] = api_key
                client.headers["Authorization"] = f"Bearer {api_key}"

            if hasattr(client, "client") and hasattr(client.client, "headers"):
                if client.client.headers is None:
                    client.client.headers = {}
                client.client.headers["X‑API‑Key"] = api_key
                client.client.headers["Authorization"] = f"Bearer {api_key}"
        return client

    @agentos_client.setter
    def agentos_client(self, value):
        self._store_agentos_client = value

    @property
    def name(self) -> Optional[str]:
        return self._override_name or super().name

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._override_metadata or {}

    def get_auth_headers(self, auth_token: Optional[str] = None) -> Optional[Dict[str, str]]:
        return self._get_auth_headers(auth_token)

    def _get_auth_headers(self, auth_token: Optional[str] = None) -> Optional[Dict[str, str]]:
        """组装访问远端Agent服务的鉴权头"""
        headers = {}
        try:
            if hasattr(super(), "_get_auth_headers"):
                headers = super()._get_auth_headers(auth_token) or {}
            elif hasattr(super(), "get_auth_headers"):
                headers = super().get_auth_headers(auth_token) or {}
        except Exception:
            pass

        api_key = self._api_key or settings.store_api_key

        if api_key:
            headers["X‑API‑Key"] = api_key
            if "Authorization" not in headers:
                headers["Authorization"] = f"Bearer {api_key}"

        return headers if headers else None

    @property
    def _agent_config(self) -> Optional[Any]:
        """重写读取远端agent配置，带上鉴权头，本地缓存配置减少http请求"""
        current_time = time.time()
        if self._cached_agent_config is not None:
            config, cached_at = self._cached_agent_config
            if current_time - cached_at < self.config_ttl:
                return config

        headers = self._get_auth_headers()
        try:
            config = self.agentos_client.get_agent(self.agent_id, headers=headers)
            self._cached_agent_config = (config, current_time)
            return config
        except Exception:
            return None

    @property
    def _config(self) -> Optional[Any]:
        """重写读取全局远端配置，带鉴权头+本地缓存"""
        current_time = time.time()
        if self._cached_config is not None:
            config, cached_at = self._cached_config
            if current_time - cached_at < self.config_ttl:
                return config

        headers = self._get_auth_headers()
        try:
            config = self.agentos_client.get_config(headers=headers)
            self._cached_config = (config, current_time)
            return config
        except Exception:
            return None

    async def get_agent_config(self) -> Any:
        """异步获取agent配置，注入鉴权头"""
        headers = self._get_auth_headers()
        return await self.agentos_client.aget_agent(self.agent_id, headers=headers)

    async def refresh_config(self) -> Optional[Any]:
        """强制刷新远端agent配置，更新本地缓存"""
        headers = self._get_auth_headers()
        config = await self.agentos_client.aget_agent(self.agent_id, headers=headers)
        self._cached_agent_config = (config, time.time())
        return config

    def arun(
        self,
        input: Any,
        *,
        stream: Optional[bool] = None,
        **kwargs
    ) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]:
        """
        运行远程 Agent，支持本地工具透明执行。
        如果绑定了本地工具：
        1. 将工具 schema 发送给远程 Agent
        2. 检查返回结果中是否有需要外部执行的工具
        3. 本地执行这些工具，然后调用 continue_run 继续
        4. 循环直到完成
        """
        _logger.info(f"StoreRemoteAgent.arun called with stream={stream}")
        # 如果存在本地工具，把工具schema传给远端大模型
        if self.local_tools:
            tools_schema = self._build_tools_schema()
            kwargs["tools"] = json.dumps(tools_schema)
            _logger.debug(f"Injecting {len(tools_schema)} local tools to remote agent call")

        # 调用父类RemoteAgent原始arun，访问远端推理服务
        result = super().arun(input, stream=stream, **kwargs)

        # 区分流式 / 非流式返回，包装工具执行循环
        if stream:
            return self._wrap_stream_with_tool_execution(result, **kwargs)
        else:
            if asyncio.iscoroutine(result):
                return self._wrap_coro_with_tool_execution(result,** kwargs)
            return result

    async def _wrap_coro_with_tool_execution(self, coro, **kwargs) -> RunOutput:
        """包装协程，非流式场景的工具执行循环"""
        run_output = await coro

        self._map_ids(run_output)

        if not self.local_tools:
            return run_output

        max_iterations = 10  # 最大循环次数，防止无限工具调用死循环
        iteration = 0

        while self._has_pending_tool_calls(run_output) and iteration < max_iterations:
            iteration += 1
            _logger.debug(f"Tool execution loop iteration {iteration}")

            if hasattr(run_output, 'tools') and run_output.tools:
                updated_tools = await self._execute_tools_locally(run_output.tools)

                run_id = getattr(run_output, 'run_id', None)
                session_id = kwargs.get('session_id')

                if run_id:
                    _logger.debug(f"Calling acontinue_run with run_id={run_id}")
                    # 把本地执行完的工具结果回传给远端agent，继续往下推理
                    run_output = await self.acontinue_run(
                        run_id=run_id,
                        updated_tools=updated_tools,
                        session_id=session_id,
                        stream=False
                    )
                    self._map_ids(run_output)
                else:
                    _logger.warning("No run_id in response, cannot continue run")
                    break

        if iteration >= max_iterations:
            _logger.warning(f"Tool execution loop reached max iterations ({max_iterations})")

        return run_output

    async def _wrap_stream_with_tool_execution(self, stream_result, **kwargs) -> AsyncIterator[RunOutputEvent]:
        """包装流式结果，SSE流式场景下的工具执行循环
        流式事件全部yield返回给上层；流结束后检测是否有待执行工具，本地执行后继续流式continue_run
        """
        collected_output = None
        print("_wrap_stream_with_tool_execution-->")
        async for event in stream_result:
            # 事件里面的agent_id覆盖为我们数据库真实id
            if hasattr(event, "agent_id") and self._override_id:
                event.agent_id = self._override_id
            if hasattr(event, "agent_name") and self._override_name:
                event.agent_name = self._override_name

            if hasattr(event, 'run_id'):
                collected_output = event

            yield event

        _logger.debug(f"Stream finished. collected_output type: {type(collected_output)}")
        print("collected_output-->", collected_output)

        # 流式输出全部推送完毕，检测是否有待处理工具调用
        if self.local_tools and collected_output and self._has_pending_tool_calls(collected_output):
            _logger.debug("Stream completed with pending tool calls, entering tool execution loop")

            max_iterations = 10
            iteration = 0

            while self._has_pending_tool_calls(collected_output) and iteration < max_iterations:
                iteration += 1

                if hasattr(collected_output, 'tools') and collected_output.tools:
                    updated_tools = await self._execute_tools_locally(collected_output.tools)

                    run_id = getattr(collected_output, 'run_id', None)
                    session_id = kwargs.get('session_id')

                    if run_id:
                        # 继续流式执行，新产生的事件继续yield出去
                        async for event in self.acontinue_run(
                            run_id=run_id,
                            updated_tools=updated_tools,
                            session_id=session_id,
                            stream=True
                        ):
                            if hasattr(event, "agent_id") and self._override_id:
                                event.agent_id = self._override_id
                            if hasattr(event, 'run_id'):
                                collected_output = event
                            yield event
                    else:
                        break

    def _map_ids(self, result: Any) -> None:
        """把返回结果对象里面agent_id/agent_name覆盖成我们数据库的真实值"""
        if self._override_id:
            if hasattr(result, "agent_id"):
                result.agent_id = self._override_id
            if hasattr(result, "agent_name"):
                result.agent_name = self.name


# 不可编辑系统提示片段：工具鉴权报错时引导用户跳转认证页面
UNEDITABLE_SYSTEM_PROMPT = (
    "\nIf the tool throws an error requiring authentication, provide the user with a Markdown "
    "link to the authentication page and prompt them to authenticate."
)

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant that has access to a variety of tools."


class AgentBuilder:
    """Constructs Agno agents with optional RAG and MCP tooling.
    底层Agent构建器核心类
    接收上层 AgentRunRequest，完成：配置归一化、模型实例化、构建全套工具链、拼装system prompt、记忆后端、技能系统
    输出本地Agent / StoreRemoteAgent实例
    """

    def __init__(self, settings: ToolsRuntimeSettings) -> None:
        self._settings = settings
        self._logger = get_logger("runtime.tools.AgentBuilder")
        self._memory_db: Optional[PostgresDb] = None  # 记忆数据库连接，复用pg连接实例

    @staticmethod
    def _is_cancellation_like_error(exc: BaseException) -> bool:
        """检测MCP客户端抛出的协程取消异常，区分普通业务异常和取消异常"""
        name = type(exc).__name__.lower()
        message = str(exc).lower()
        return "cancel" in name or "cancel scope" in message

    # ------------------------------------------------------------------
    # Public API
    async def build_agent(
        self,
        request: AgentRunRequest,
        internal_agent: Optional["InternalAgent"] = None,
    ) -> Union[Agent, RemoteAgent]:
        """Build an agent configured for the given request.
        对外公开入口，上层调用这个方法获取agent实例
        Args:
            request: agent运行请求，包含全部运行时配置
            internal_agent: 数据库读取出来的agent数据库模型对象
        """
        # # 1. Handle Remote Store Agents
        # if internal_agent and getattr(internal_agent, "is_remote_store_agent", False):
        #     return await self._build_remote_store_agent(request, internal_agent)

        # 2. Handle Local Agents 构建本地运行Agent
        return await self._build_local_agent(request, internal_agent)

    async def _build_remote_store_agent(
        self,
        request: AgentRunRequest,
        internal_agent: "InternalAgent",
    ) -> StoreRemoteAgent:
        """Helper to construct a StoreRemoteAgent.
        构建远程推理Agent（大模型推理跑在远端store服务，工具在本地执行）
        """
        api_key = None
        if request.project_id:
            try:
                credential = await api_service_client.get_store_credential(request.project_id)
                if credential:
                    api_key = credential.get("api_key")
            except Exception as e:
                self._logger.warning("Failed to fetch store credential", error=str(e))

        if not api_key:
            api_key = settings.store_api_key

        local_tools = []
        if internal_agent.tools:
            try:
                local_tools = await self._build_mcp_tools_from_agent(
                    internal_agent,
                    request.session_id,
                    request.user_id,
                    project_id=request.project_id,
                )
            except Exception as e:
                self._logger.warning("Failed to build local tools for remote agent", error=str(e))

        self._logger.debug(
            "Creating RemoteAgent",
            agent_id=internal_agent.store_agent_id,
            base_url=internal_agent.remote_agent_url
        )
        return StoreRemoteAgent(
            base_url=internal_agent.remote_agent_url,
            agent_id=internal_agent.store_agent_id,
            timeout=60.0,
            override_id=str(internal_agent.id),
            override_name=internal_agent.name,
            api_key=api_key,
            tools=local_tools,
        )

    async def _build_local_agent(
        self,
        request: AgentRunRequest,
        internal_agent: Optional["InternalAgent"] = None,
    ) -> Agent:
        """Helper to construct a local Agno Agent.
        构建本地完整Agent实例：模型、全套工具、提示词、记忆、技能全部组装完成
        """
        config = self._normalize_config(request.config)
        # 构建全部工具列表：RAG/MCP/插件/http/设备工具/自定义业务工具
        tools = await self._build_tools(
            config,
            request.session_id,
            request.user_id,
            internal_agent=internal_agent,
            project_id=request.project_id,
            agent_id=request.agent_id,
            request_id=request.request_id,
        )

        # 加载skills技能对象
        skills_obj = None
        skills_enabled = request.skills_enabled if request.skills_enabled is not None else True
        if skills_enabled and request.project_id:
            try:
                skills_obj = self._build_skills(request.project_id)
                if skills_obj:
                    self._logger.debug(
                        "Skills object built for agent",
                        project_id=request.project_id,
                    )
            except Exception as exc:
                self._logger.warning(
                    "Skill loading failed, continuing without skills",
                    project_id=request.project_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        # 实例化LLM模型对象
        model = self._initialize_model(config)
        # 拼接最终system指令
        instructions = self._compose_system_prompt(config.system_prompt)
        enable_memory = request.enable_memory or bool(config.enable_memory)

        self._logger.debug(
            "Creating local agent",
            tool_count=len(tools),
            model_name=config.model_name,
        )

        try:
            agent_kwargs: Dict[str, Any] = {
                "model": model,
                "tools": tools,
                "instructions": instructions,
                "additional_context": config.system_message,
                "expected_output": config.expected_output,
                "description": "Tools agent with MCP and RAG support",
                "markdown": config.markdown if config.markdown is not None else True,
                "add_datetime_to_context": config.add_datetime_to_context if config.add_datetime_to_context is not None else True,
                "add_location_to_context": config.add_location_to_context if config.add_location_to_context is not None else False,
                "timezone_identifier": config.timezone_identifier,
                "tool_call_limit": config.tool_call_limit,
                "telemetry": False,
                "debug_mode": True,
                "debug_level": 2
            }

            if skills_obj is not None:
                agent_kwargs["skills"] = skills_obj

            if request.session_id:
                agent_kwargs["session_id"] = request.session_id
            if request.user_id:
                agent_kwargs["user_id"] = request.user_id

            # 开启记忆：注入postgres记忆数据库、memory_manager
            if enable_memory:
                memory_manager, memory_db = self._ensure_memory_backend(model)
                agent_kwargs.update(
                    db=memory_db,
                    memory_manager=memory_manager,
                    enable_agentic_memory=True,
                    enable_user_memories=True,
                    add_memories_to_context=True,
                    add_history_to_context=True,
                    num_history_runs=config.num_history_runs if config.num_history_runs is not None else 5,
                )

            return Agent(**agent_kwargs)
        except Exception as exc:
            raise InvalidConfigurationError(
                "Failed to create Agent instance",
                tools_count=len(tools),
                error=str(exc),
            ) from exc

    # ------------------------------------------------------------------
    # Configuration helpers
    def _normalize_config(self, config: Optional[AgentConfig]) -> AgentConfig:
        """Apply runtime defaults to the incoming configuration.
        配置归一化：把传入的config为空字段填充全局运行时默认值
        """
        merged = (config or AgentConfig()).model_copy(deep=True)
        base = self._settings.model

        merged.model_name = merged.model_name or base.name
        merged.temperature = merged.temperature if merged.temperature is not None else base.temperature
        merged.max_tokens = merged.max_tokens if merged.max_tokens is not None else base.max_tokens
        merged.system_prompt = merged.system_prompt or base.system_prompt

        return merged

    def _compose_system_prompt(
        self,
        configured_prompt: Optional[str],
    ) -> str:
        """Compose the final system prompt with json‑render schema.
        组装最终system提示词：用户指令 + json输出格式schema + 固定不可修改提示片段
        """
        prompt = configured_prompt or DEFAULT_SYSTEM_PROMPT

        try:
            json_render_mgr = JsonRenderSchemaManager()
            json_render_block = json_render_mgr.generate_system_prompt(
                include_schema=True,
                include_examples=True,
            )
            prompt = f"{prompt}\n\n{json_render_block}"
            self._logger.debug("json‑render schema injected into system prompt")
        except Exception as exc:
            self._logger.warning(
                "Failed to inject json‑render schema into system prompt",
                error=str(exc),
            )

        return f"{prompt}{UNEDITABLE_SYSTEM_PROMPT}"

    def resolve_model_instance(self, config: Optional[AgentConfig] = None) -> Any:
        """Public helper to obtain a model instance using runtime defaults."""
        normalized = self._normalize_config(config)
        return self._initialize_model(normalized)

    # ------------------------------------------------------------------
    # Tool preparation
    async def _build_tools(
        self,
        config: AgentConfig,
        session_id: Optional[str],
        user_id: Optional[str],
        internal_agent: Optional["InternalAgent"] = None,
        project_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> List[Any]:
        """
        总工具构建入口，依次组装：
        RAG工具 → Workflow工作流工具 → MCP工具 → 设备MCP工具 → 自定义业务工具
        某一类工具构建失败不阻断整个agent，只打warning日志，跳过该类工具继续运行
        """
        tools: List[Any] = []

        try:
            tools.extend(await self._build_rag_tools(config.rag))
        except Exception as exc:
            self._logger.warning(
                "RAG tool setup failed, continuing without RAG tools",
                error=str(exc),
                error_type=type(exc).__name__,
            )

        try:
            tools.extend(await self._build_workflow_tools(config.workflow))
        except Exception as exc:
            self._logger.warning(
                "Workflow tool setup failed, continuing without workflow tools",
                error=str(exc),
                error_type=type(exc).__name__,
            )

        # 优先使用数据库agent绑定的tools，没有才使用config.mcp_config
        if internal_agent and internal_agent.tools:
            try:
                tools.extend(
                    await self._build_mcp_tools_from_agent(
                        internal_agent,
                        session_id,
                        user_id,
                        project_id=project_id
                    )
                )
            except (MCPConnectionError, MCPToolError, MCPAuthenticationError) as exc:
                self._logger.warning(
                    "MCP tool setup from agent failed, continuing without MCP tools",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            except Exception as exc:
                self._logger.warning(
                    "Unexpected error during MCP tool setup from agent, continuing without MCP tools",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        else:
            try:
                tools.extend(await self._build_mcp_tools(config.mcp_config, session_id, user_id))
            except (MCPConnectionError, MCPToolError, MCPAuthenticationError) as exc:
                self._logger.warning(
                    "MCP tool setup failed, continuing without MCP tools",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
            except Exception as exc:
                self._logger.warning(
                    "Unexpected error during MCP tool setup, continuing without MCP tools",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

        # 绑定设备的情况下，加载设备MCP工具
        if internal_agent and getattr(internal_agent, "bound_device_id", None):
            try:
                device_tools = await self._build_device_mcp_tools(internal_agent)
                tools.extend(device_tools)
            except Exception as exc:
                self._logger.warning(
                    "Device MCP tool setup failed, continuing without device tools",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    device_id=getattr(internal_agent, "bound_device_id", None),
                )

        # 构建系统内置自定义工具：会话转交、用户情绪、用户标签等
        if agent_id:
            try:
                tools.extend(
                    self._build_custom_tools(
                        agent_id=agent_id,
                        session_id=session_id,
                        user_id=user_id,
                        project_id=project_id,
                        request_id=request_id,
                    )
                )
            except Exception as exc:
                self._logger.warning(
                    "Custom tool setup failed, continuing without custom tools",
                    error=str(exc),
                    error_type=type(exc).__name__,
                    agent_id=agent_id,
                )

        return tools

    def _build_custom_tools(
        self,
        *,
        agent_id: str,
        session_id: Optional[str],
        user_id: Optional[str],
        project_id: Optional[str],
        request_id: Optional[str],
    ) -> List[Any]:
        """Build agent‑scoped custom tools for user operations and handoff.
        系统内置业务工具：会话转交、获取用户信息、用户情绪识别、给用户打标签
        """
        from app.runtime.tools.custom import (
            create_handoff_tool,
            create_user_info_tool,
            create_user_sentiment_tool,
            create_user_tag_tool,
        )

        tools: List[Any] = []
        tool_context = {
            "agent_id": agent_id,
            "session_id": session_id,
            "user_id": user_id,
            "project_id": project_id,
            "request_id": request_id,
        }
        for creator in (
            create_handoff_tool,
            create_user_info_tool,
            create_user_sentiment_tool,
            create_user_tag_tool,
        ):
            created = creator(**tool_context)
            if isinstance(created, list):
                tools.extend(created)
            else:
                tools.append(created)

        return tools

    def _build_skills(self, project_id: str) -> Optional[Any]:
        """Build an Agno Skills object that loads project + official skills.
        加载技能系统：项目私有技能 + 官方公共技能；过滤掉禁用的skill
        返回Agno Skills对象，会自动把技能描述注入system prompt、注册对应工具
        """
        try:
            from agno.skills import Skills, LocalSkills
        except ImportError:
            self._logger.warning(
                "agno.skills not available; skipping skill loading"
            )
            return None

        from pathlib import Path
        from app.config import settings
        from app.services.skill_file_service import SkillFileService

        base_dir = Path(settings.skills_base_dir)
        loaders: list[LocalSkills] = []

        skill_service = SkillFileService(settings.skills_base_dir)
        disabled_skills = skill_service.get_disabled_skills(project_id)

        def _collect_enabled_loaders(directory: Path) -> None:
            """扫描目录，只收集启用的skill文件夹（存在SKILL.md，不在禁用列表）"""
            if not directory.exists() or not directory.is_dir():
                return
            try:
                for child in sorted(directory.iterdir()):
                    if (
                        child.is_dir()
                        and not child.name.startswith(".")
                        and child.name not in disabled_skills
                        and (child / "SKILL.md").exists()
                    ):
                        loaders.append(LocalSkills(str(child)))
            except OSError:
                pass

        # 1.项目私有技能
        _collect_enabled_loaders(base_dir / project_id)
        # 2.官方共享技能
        _collect_enabled_loaders(base_dir / "_official")

        if not loaders:
            self._logger.debug(
                "No enabled skill directories found",
                project_id=project_id,
                base_dir=str(base_dir),
            )
            return None

        self._logger.debug(
            "Building Skills object",
            project_id=project_id,
            loader_count=len(loaders),
            disabled_count=len(disabled_skills),
        )
        return Skills(loaders=loaders)

    async def _build_rag_tools(self, rag_config: Optional[RagConfig]) -> List[Any]:
        """构建RAG检索工具，每个知识库集合对应一个RAG工具实例"""
        if not rag_config or not rag_config.rag_url or not rag_config.collections:
            return []

        tools: List[Any] = []
        for collection in rag_config.collections:
            try:
                tool = await create_rag_tool(
                    rag_config.rag_url,
                    collection,
                    project_id=rag_config.project_id,
                    filters=rag_config.filters,
                )
                tools.append(tool)
            except Exception as exc:
                self._logger.warning(
                    "Failed to create RAG tool for collection, skipping",
                    collection=collection,
                    rag_url=rag_config.rag_url,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
        return tools

    async def _build_workflow_tools(self, workflow_config: Optional[WorkflowConfig]) -> List[Any]:
        """构建工作流调用工具，用于Agent调用其他工作流"""
        if not workflow_config or not workflow_config.workflow_url or not workflow_config.workflows:
            return []

        try:
            return await create_workflow_tools(
                workflow_config.workflow_url,
                workflow_config.workflows,
                project_id=workflow_config.project_id,
            )
        except Exception as exc:
            self._logger.warning(
                "Failed to create workflow tools, skipping",
                workflows=workflow_config.workflows,
                workflow_url=workflow_config.workflow_url,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return []

    async def _build_mcp_tools(
        self,
        mcp_config: Optional[MCPConfig],
        session_id: Optional[str],
        user_id: Optional[str],
    ) -> List[Any]:
        """通过MCPConfig配置连接MCP服务，拉取工具列表，转换成Agno可用工具对象"""
        if not mcp_config or not mcp_config.url:
            return []

        headers = await self._build_mcp_headers(mcp_config, session_id, user_id)
        server_url = mcp_config.url.rstrip("/") + "/mcp"
        requested_tools = set(mcp_config.tools or [])
        added_tool_names: set[str] = set()
        fetched_tools: List[Any] = []

        try:
            async with streamablehttp_client(server_url, headers=headers) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    try:
                        await session.initialize()
                    except Exception as exc:
                        raise MCPConnectionError(
                            "Failed to initialize MCP session",
                            mcp_url=server_url,
                            error=str(exc),
                        ) from exc
                    # 分页获取MCP服务全部工具
                    cursor = None
                    while True:
                        try:
                            tool_list_page = await session.list_tools(cursor=cursor)
                        except Exception as exc:
                            raise MCPToolError(
                                "Failed to list MCP tools",
                                mcp_url=server_url,
                                cursor=cursor,
                                error=str(exc),
                            ) from exc
                        if not tool_list_page or not tool_list_page.tools:
                            break

                        for mcp_tool in tool_list_page.tools:
                            if requested_tools and mcp_tool.name not in requested_tools:
                                continue
                            if mcp_tool.name in added_tool_names:
                                continue

                            try:
                                agno_tool = create_agno_mcp_tool(
                                    mcp_tool,
                                    mcp_server_url=server_url,
                                    headers=headers,
                                )
                                if mcp_config.auth_required:
                                    agno_tool = wrap_mcp_authenticate_tool(agno_tool)
                                fetched_tools.append(agno_tool)
                                added_tool_names.add(mcp_tool.name)
                            except Exception as exc:
                                self._logger.warning(
                                    "Failed to convert MCP tool, skipping",
                                    tool_name=mcp_tool.name,
                                    mcp_url=server_url,
                                    error=str(exc),
                                    error_type=type(exc).__name__,
                                )

                        cursor = tool_list_page.nextCursor
                        if not cursor or (
                            requested_tools and len(added_tool_names) == len(requested_tools)
                        ):
                            break
        except MCPConnectionError:
            raise
        except MCPToolError:
            raise
        except Exception as exc:
            raise MCPToolError(
                "Unexpected error during MCP tool setup",
                mcp_url=server_url,
                error=str(exc),
            ) from exc
        except BaseException as exc:
            if self._is_cancellation_like_error(exc):
                raise MCPConnectionError(
                    "MCP setup canceled while initializing tools",
                    mcp_url=server_url,
                    error=str(exc),
                ) from exc
            raise

        self._logger.debug(
            "MCP tools setup completed",
            mcp_url=server_url,
            tools_fetched=len(fetched_tools),
            tools_requested=len(requested_tools) if requested_tools else "all",
        )

        return fetched_tools

    async def _fetch_mcp_tools_from_endpoint(
        self,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None,
        requested_tools: Optional[set[str]] = None,
    ) -> List[Function]:
        """
        从 MCP 网关http接口获取工具定义，不走MCP长连接协议，走http rest接口拉取工具schema
        用于Store商店来源的MCP工具
        """
        tools: List[Function] = []
        server_url = endpoint.rstrip("/")

        if server_url.endswith("/http"):
            tools_url = server_url[:-5] + "/tools"
        elif server_url.endswith("/sse"):
            tools_url = server_url[:-4] + "/tools"
        else:
            tools_url = server_url + "/tools"

        try:
            self._logger.info(
                "Fetching MCP tools from gateway",
                endpoint=endpoint,
                tools_url=tools_url,
                requested_tools=list(requested_tools) if requested_tools else None,
                header_keys=list(headers.keys()) if headers else None,
            )
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(tools_url, headers=headers)
                self._logger.info(
                    "MCP gateway response received",
                    tools_url=tools_url,
                    status_code=response.status_code,
                    content_type=response.headers.get("content‑type"),
                )
                response.raise_for_status()

                data = response.json()
                print("data-->", data)
                self._logger.debug(
                    "MCP gateway response parsed",
                    tools_url=tools_url,
                    response_keys=list(data.keys()) if isinstance(data, dict) else None,
                    tool_count=len(data.get("tools", [])) if isinstance(data, dict) else None,
                )
                tool_list = data.get("tools", [])

                for tool_def in tool_list:
                    tool_name = tool_def.get("name")

                    if requested_tools and tool_name not in requested_tools:
                        continue

                    mcp_tool = types.SimpleNamespace(
                        name=tool_name,
                        description=tool_def.get("description", ""),
                        inputSchema=tool_def.get("inputSchema", {"type": "object", "properties": {}}),
                    )

                    tool_func = create_agno_mcp_tool(
                        mcp_tool,
                        mcp_server_url=server_url,
                        headers=headers,
                    )
                    tools.append(tool_func)

                self._logger.debug(
                    "Successfully fetched tool definitions from MCP gateway",
                    tools_url=tools_url,
                    tool_count=len(tools),
                )

        except httpx.HTTPStatusError as e:
            response_text = ""
            try:
                response_text = e.response.text
            except Exception:
                response_text = ""
            if response_text and len(response_text) > 1000:
                response_text = response_text[:1000] + "...(truncated)"
            self._logger.warning(
                "MCP gateway returned error status",
                endpoint=endpoint,
                tools_url=tools_url,
                status_code=e.response.status_code,
                response_text=response_text,
            )
        except Exception as e:
            print(f"[ERROR] Failed to fetch MCP tools from endpoint: {e!r}")
            print(f"[ERROR] endpoint={endpoint}, tools_url={tools_url}")
            print(f"[ERROR] Traceback:\n{traceback.format_exc()}")
            self._logger.warning(
                f"Failed to fetch MCP tools from endpoint, tools will not be available. error={e!r}",
                endpoint=endpoint,
                tools_url=tools_url,
                requested_tools=list(requested_tools) if requested_tools else None,
                error_type=type(e).__name__,
            )

        return tools

    async def _build_mcp_tools_from_agent(
        self,
        internal_agent: "InternalAgent",
        session_id: Optional[str],
        user_id: Optional[str],
        project_id: Optional[str] = None,
    ) -> List[Any]:
        """Build MCP tools from InternalAgent.tools configuration.
        读取数据库Agent绑定的全部工具，区分transport_type：plugin / http_webhook / mcp‑http / stdio
        分组分别构建插件工具、http工具、MCP工具
        """
        enabled_tools = [
            t for t in internal_agent.tools
            if (t.tool_type == "MCP" or t.transport_type == "http_webhook") and t.enabled
        ]
        if not enabled_tools:
            return []

        self._logger.debug("Loading tools from agent", agent_id=str(internal_agent.id), count=len(enabled_tools))

        tools_by_endpoint: Dict[str, List[AgentTool]] = {}
        plugin_tools: List[AgentTool] = []
        http_tools: List[AgentTool] = []
        for t in enabled_tools:
            if t.transport_type == "plugin":
                plugin_tools.append(t)
            elif t.transport_type == "http_webhook":
                http_tools.append(t)
            elif t.endpoint:
                tools_by_endpoint.setdefault(t.endpoint, []).append(t)

        headers = await self._build_auth_headers(session_id, user_id, project_id)

        tools: List[Any] = []
        tools.extend(self._build_plugin_tools(plugin_tools, session_id, user_id, str(internal_agent.id)))
        tools.extend(self._build_http_webhook_tools(http_tools))

        mcp_tools, stdio_cmds = await self._build_mcp_server_instances(tools_by_endpoint, headers)
        tools.extend(mcp_tools)

        if stdio_cmds:
            tools.extend(await self._build_multi_mcp_stdio(stdio_cmds))

        return tools

    async def _build_auth_headers(self, session_id: Optional[str], user_id: Optional[str], project_id: Optional[str]) -> Dict[str, str]:
        """构建工具调用统一鉴权头：X‑Session‑ID X‑User‑ID X‑API‑Key"""
        headers = {}
        if session_id:
            headers["X‑Session‑ID"] = session_id
        if user_id:
            headers["X‑User‑ID"] = user_id

        if project_id:
            try:
                credential = await api_service_client.get_store_credential(project_id)
                if credential and credential.get("api_key"):
                    headers["X‑API‑Key"] = credential["api_key"]
            except Exception:
                pass

        if "X‑API‑Key" not in headers and settings.store_api_key:
            headers["X‑API‑Key"] = settings.store_api_key
        return headers

    def _build_plugin_tools(self, plugin_tools: List[AgentTool], session_id: Optional[str], user_id: Optional[str], agent_id: str) -> List[Any]:
        """构建插件工具，对应之前PluginManager插件运行时，调用unix‑socket/tcp和插件进程通信"""
        instances = []
        for t in plugin_tools:
            try:
                config = t.base_config or {}
                plugin_id = config.get("plugin_id")
                tool_name = config.get("tool_name")
                if not plugin_id or not tool_name:
                    continue

                props = {}
                req = []
                for p in config.get("parameters", []):
                    p_name = p.get("name")
                    p_type = p.get("type", "string")
                    prop = {"type": "string" if p_type == "enum" else p_type, "description": p.get("description", "")}
                    if p_type == "enum" and "enum_values" in p:
                        prop["enum"] = p["enum_values"]
                    props[p_name] = prop
                    if p.get("required"):
                        req.append(p_name)

                instances.append(create_plugin_tool(
                    plugin_id=plugin_id,
                    tool_name=tool_name,
                    title=t.tool_name,
                    description=config.get("description"),
                    parameters={"type": "object", "properties": props, "required": req} if req else {"type": "object", "properties": props},
                    session_id=session_id,
                    user_id=user_id,
                    agent_id=agent_id,
                ))
            except Exception as exc:
                self._logger.warning(f"Failed to create plugin tool {t.tool_name}", error=str(exc))
        return instances

    def _build_http_webhook_tools(self, http_tools: List[AgentTool]) -> List[Any]:
        """构建http webhook工具：直接http请求调用外部http接口作为工具"""
        instances = []
        for t in http_tools:
            try:
                config = t.base_config or {}
                if not t.endpoint:
                    continue
                instances.append(create_http_tool(
                    name=t.tool_name,
                    description=config.get("description") or t.tool_name,
                    endpoint=t.endpoint,
                    method=config.get("method", "POST"),
                    headers=config.get("headers"),
                    parameters=config.get("parameters"),
                    timeout=config.get("timeout", 30.0),
                ))
            except Exception as exc:
                self._logger.warning(f"Failed to create HTTP tool {t.tool_name}", error=str(exc))
        return instances

    async def _build_mcp_server_instances(self, tools_by_endpoint: Dict[str, List[AgentTool]], headers: Dict[str, str]) -> tuple[List[Any], List[str]]:
        """
        区分MCP来源：
        STORE商店工具 → http网关接口拉取工具schema
        LOCAL本地MCP服务 → 建立streamable‑http/sse长连接MCPTools对象
        stdio命令的返回命令列表，交给上层MultiMCPTools处理
        """
        """Helper to construct individual MCP server instances (HTTP/SSE/stdio).

        Routing logic:
        - STORE tools → ``_fetch_mcp_tools_from_endpoint`` (ToolStore gateway with API Key auth)
        - LOCAL tools → ``MCPTools`` standard MCP direct connection (internal services)
        """
        instances = []
        stdio_cmds = []
        for endpoint, endpoint_tools in tools_by_endpoint.items():
            try:
                transport = endpoint_tools[0].transport_type or "http"
                if transport == "stdio":
                    stdio_cmds.append(endpoint)
                    continue

                server_url = endpoint.rstrip("/")

                # Use tool_source_type to decide connection mode (not headers)
                is_store_tool = any(
                    t.tool_source_type == "STORE"
                    for t in endpoint_tools
                )

                if is_store_tool and headers:
                    # ToolStore gateway path – needs API Key authentication
                    fetched = await self._fetch_mcp_tools_from_endpoint(server_url, headers)
                    if fetched:
                        instances.extend(fetched)
                    else:
                        self._logger.warning("Dynamic MCP fetch failed", endpoint=endpoint)
                else:
                    # Standard MCP direct connection (LOCAL tools / internal services)
                    mcp = MCPTools(
                        transport="streamable-http" if transport == "http" else "sse",
                        url=server_url,
                    )
                    await mcp.connect()
                    instances.append(mcp)
            except Exception as exc:
                self._logger.warning(f"Failed to setup MCP server {endpoint}", error=str(exc))
            except BaseException as exc:
                if self._is_cancellation_like_error(exc):
                    self._logger.warning(
                        "MCP server setup canceled, skipping endpoint",
                        endpoint=endpoint,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                    continue
                raise
        return instances, stdio_cmds

    async def _build_device_mcp_tools(self, internal_agent: "InternalAgent") -> List[Any]:
        """Create callable MCP function tools for the agent's bound device.

        Unlike generic MCP toolkit wiring, this resolves device MCP tools at
        build time and returns function tools directly. This avoids runtime
        toolkit initialization failures from aborting the whole agent stream.
        """
        device_id = internal_agent.bound_device_id
        if not device_id:
            return []

        endpoint = settings.device_control_mcp_endpoint.replace("{device_id}", str(device_id))
        self._logger.info(
            "Connecting to device MCP",
            device_id=device_id,
            endpoint=endpoint,
        )

        requested_tool_names = {
            t.tool_name
            for t in (internal_agent.tools or [])
            if getattr(t, "enabled", True)
            and t.tool_type == "MCP"
            and t.tool_name
        }
        added_tool_names: set[str] = set()
        device_tools: List[Any] = []

        try:
            async with streamablehttp_client(endpoint) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    cursor = None
                    while True:
                        tool_list_page = await session.list_tools(cursor=cursor)
                        if not tool_list_page or not tool_list_page.tools:
                            break

                        for mcp_tool in tool_list_page.tools:
                            if requested_tool_names and mcp_tool.name not in requested_tool_names:
                                continue
                            if mcp_tool.name in added_tool_names:
                                continue

                            try:
                                device_tools.append(
                                    create_agno_mcp_tool(
                                        mcp_tool,
                                        mcp_server_url=endpoint,
                                        headers=None,
                                    )
                                )
                                added_tool_names.add(mcp_tool.name)
                            except Exception as exc:  # noqa: BLE001
                                self._logger.warning(
                                    "Failed to convert device MCP tool, skipping",
                                    device_id=str(device_id),
                                    endpoint=endpoint,
                                    tool_name=mcp_tool.name,
                                    error=str(exc),
                                    error_type=type(exc).__name__,
                                )

                        cursor = tool_list_page.nextCursor
                        if not cursor:
                            break
        except Exception as exc:  # noqa: BLE001
            raise MCPConnectionError(
                "Device MCP setup failed during tool discovery",
                mcp_url=endpoint,
                error=str(exc),
            ) from exc
        except BaseException as exc:
            if self._is_cancellation_like_error(exc):
                raise MCPConnectionError(
                    "Device MCP setup canceled during tool discovery",
                    mcp_url=endpoint,
                    error=str(exc),
                ) from exc
            raise

        self._logger.debug(
            "Device MCP tools setup completed",
            device_id=str(device_id),
            endpoint=endpoint,
            tools_fetched=len(device_tools),
            tools_requested=len(requested_tool_names) if requested_tool_names else "all",
        )
        return device_tools

    async def _build_multi_mcp_stdio(self, stdio_cmds: List[str]) -> List[Any]:
        """Helper to construct MultiMCPTools for stdio servers."""
        try:
            multi = MultiMCPTools(stdio_cmds, allow_partial_failure=True)
            await multi.connect()
            return [multi]
        except Exception as exc:
            self._logger.error("MultiMCPTools initialization failed", error=str(exc))
            return []
        except BaseException as exc:
            if self._is_cancellation_like_error(exc):
                self._logger.warning(
                    "MultiMCPTools setup canceled, skipping stdio MCP tools",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return []
            raise

    def get_memory_backend(self, model: Any) -> tuple[MemoryManager, PostgresDb]:
        """Expose shared memory backend for external consumers (keyed by model)."""
        return self._ensure_memory_backend(model)


    def _ensure_memory_backend(self, model: Any) -> tuple[MemoryManager, PostgresDb]:
        """Always create a fresh MemoryManager for the provided model; reuse only the PostgresDb connection."""
        try:
            db = self._memory_db
            if db is None:
                db_url = settings.get_database_url(sync=True)
                self._logger.debug("Initializing Postgres memory backend", db_url=db_url)
                db = PostgresDb(db_url=db_url)
                self._memory_db = db

            # Create a new MemoryManager for each request to avoid stale model references
            memory_manager = MemoryManager(model=model, db=db)
            return memory_manager, db
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "Failed to initialize memory manager",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise InvalidConfigurationError(
                "Failed to initialize memory backend",
                error=str(exc),
            ) from exc

    async def _build_mcp_headers(
        self,
        mcp_config: MCPConfig,
        session_id: Optional[str],
        user_id: Optional[str],
    ) -> Optional[Dict[str, str]]:
        if not mcp_config.auth_required:
            return None

        supabase_token = self._settings.supabase.access_token
        if not supabase_token:
            self._logger.debug("No Supabase token available for MCP authentication")
            raise MCPAuthenticationError("Supabase access token is required for MCP authentication")

        try:
            tokens = await get_mcp_access_token(supabase_token, mcp_config.url)
        except Exception as exc:  # noqa: BLE001
            raise MCPAuthenticationError(
                "Failed to fetch MCP access token",
                mcp_url=mcp_config.url,
                session_id=session_id,
                user_id=user_id,
            ) from exc

        return {"Authorization": f"Bearer {tokens['access_token']}"}

    # ------------------------------------------------------------------
    # Model helpers
    def initialize_model(self, config: AgentConfig) -> Any:  # pragma: no cover - backwards compatibility
        return self._initialize_model(config)

    def _initialize_model(self, config: AgentConfig) -> Any:
        model_name = config.model_name or self._settings.model.name
        if not model_name:
            raise MissingConfigurationError("Model name is required", config_key="model_name")

        creds = config.provider_credentials
        if not creds:
            raise MissingConfigurationError("LLM provider credentials required", model_name=model_name)
       
        api_key = creds.api_key
        if not api_key:
            raise MissingConfigurationError(f"Missing API key for {model_name}", model_name=model_name)

        # Validation
        if config.temperature is not None and not (0 <= config.temperature <= 2):
            raise InvalidConfigurationError("Temperature must be 0-2", temperature=config.temperature)
        if config.max_tokens is not None and config.max_tokens <= 0:
            raise InvalidConfigurationError("max_tokens must be positive", max_tokens=config.max_tokens)

        provider_kind = (creds.provider_kind or "").lower()
        model_kwargs = {
            "id": model_name,
            "api_key": api_key,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }

        try:
            if provider_kind in {"openai", "openai_compatible"}:
                model_kwargs.update({
                    "role_map": {"system": "system", "user": "user", "assistant": "assistant", "tool": "tool", "model": "assistant"},
                    "base_url": creds.api_base_url,
                    "organization": creds.organization,
                    "timeout": creds.timeout,
                })
                return OpenAIChat(**{k: v for k, v in model_kwargs.items() if v is not None})

            if provider_kind == "anthropic":
                if creds.timeout:
                    model_kwargs["timeout"] = creds.timeout
                return Claude(**{k: v for k, v in model_kwargs.items() if v is not None})

            if provider_kind == "google":
                model_kwargs.update({"base_url": creds.api_base_url, "timeout": creds.timeout})
                return Gemini(**{k: v for k, v in model_kwargs.items() if v is not None})

        except Exception as exc:
            raise InvalidConfigurationError(f"Failed to init {provider_kind} model", model_name=model_name, error=str(exc)) from exc

        raise InvalidConfigurationError(
            f"Unsupported provider: {provider_kind}", 
            model_name=model_name, 
            supported=["openai", "openai_compatible", "anthropic", "google"]
        )
