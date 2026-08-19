"""Build direct single‑agent runtime instances."""
# AgnoAgentBuilder：基于执行上下文 AgentExecutionContext，组装出可运行的 Agno Agent 实例
# 职责：把上层传过来的上下文，翻译成底层工具运行时的 AgentRunRequest / AgentConfig，调用通用 AgentBuilder 完成真正构建

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from agno.agent import Agent, RemoteAgent  # Agno库核心对象：本地Agent / 远程Agent

from app.config import settings
from app.core.logging import get_logger
from app.models.internal import AgentExecutionContext
from app.runtime.tools.builder.agent_builder import AgentBuilder
from app.runtime.tools.config import ToolsRuntimeSettings
from app.runtime.tools.models import AgentConfig, AgentRunRequest, MCPConfig, RagConfig, WorkflowConfig
# 把调度层的执行上下文 AgentExecutionContext，翻译成底层 Agno 库可以直接跑的 Agent 实例。
# 它处在中间适配层，不做大模型推理，不干工具调用，只做数据组装、字段映射、配置拼装。

@dataclass
class BuiltAgent:
    """Container holding the constructed runnable agent.
    包装返回结构体，承载构建完成可直接运行的 Agent / RemoteAgent 对象
    """
    agent: Agent | RemoteAgent


class AgnoAgentBuilder:
    """Build a single runnable Agno agent from the resolved execution context.
    专门用于从 AgentExecutionContext（调度层上下文）构建 Agno 运行时Agent实例
    这一层属于**调度层适配器**：做模型字段映射，实际构造逻辑委托给下层通用 AgentBuilder
    """

    def __init__(self, settings_obj: Optional[ToolsRuntimeSettings] = None) -> None:
        # 优先传入运行时配置，没有就读取全局settings
        runtime_settings = settings_obj or settings.tools_runtime
        # 底层通用Agent构建器，真正负责拼装模型、工具、记忆、MCP、RAG
        self._agent_builder = AgentBuilder(runtime_settings)
        self._logger = get_logger("runtime.supervisor.agents.builder")

    async def build_agent(self, context: AgentExecutionContext) -> BuiltAgent:
        """Build the direct agent for one execution request.
        根据一次请求的执行上下文，完整构建一个Agno Agent实例
        :param context: Supervisor层的执行上下文，包含agent数据库对象、请求参数、链路ID、开关配置
        :return: BuiltAgent包装对象，给到AgnoAgentRunner去执行run/stream
        """
        # 组装下层工具运行时需要的请求对象 AgentRunRequest
        request = AgentRunRequest(
            message=context.message,                     # 用户提问
            config=self._build_agent_config(context),    # 生成AgentConfig（模型、提示词、MCP/RAG/工作流全部在这里）
            session_id=context.session_id,
            user_id=context.user_id,
            project_id=context.project_id,
            agent_id=str(context.agent.id),
            request_id=context.request_id,
            skills_enabled=context.agent.skills_enabled,
            enable_memory=context.enable_memory,         # 是否开启记忆开关
        )

        # 调用底层真正的构建逻辑，产出 agno 库的 Agent / RemoteAgent 对象
        agno_agent = await self._agent_builder.build_agent(request, internal_agent=context.agent)

        # 覆盖运行时id、name，保证事件、取消逻辑使用数据库持久化的agent_id，防止内部生成随机id
        agno_agent.id = str(context.agent.id)
        agno_agent.name = context.agent.name or getattr(agno_agent, "name", "Agent")

        # 往agent.metadata塞入链路追踪元数据，事件日志、埋点可以拿到project_id/agent_id/request_id
        try:
            metadata = dict(context.agent.config or {})
            metadata.update(
                {
                    "agent_id": str(context.agent.id),
                    "project_id": context.project_id,
                    "request_id": context.request_id,
                }
            )
            agno_agent.metadata = metadata
        except Exception:  # pragma: no cover - best effort metadata enrichment
            # metadata附加属于增强能力，失败不阻断agent运行，仅打debug日志
            self._logger.debug("Skipping runtime agent metadata update", agent_id=str(context.agent.id))

        return BuiltAgent(agent=agno_agent)

    def _build_agent_config(self, context: AgentExecutionContext) -> AgentConfig:
        """Build the effective AgentConfig for a single runtime execution.
        核心映射函数：把上层 AgentExecutionContext + 数据库agent配置，转换成下层运行时 AgentConfig
        组装MCP配置、RAG知识库配置、Workflow工作流配置，合并数据库存储配置 + 当前请求传入的覆盖参数
        """
        # 读取数据库保存的agent自定义配置字典
        config: Dict[str, Any] = dict(context.agent.config or {})

        # ========== MCP工具服务配置 ==========
        mcp_config = None
        # 同时满足：上下文传入mcp_url，并且agent绑定了启用的工具，则生成MCPConfig
        if context.mcp_url and context.agent.tools:
            mcp_config = MCPConfig(
                url=context.mcp_url,
                # 只取已经启用的工具
                tools=[tool.tool_name for tool in context.agent.tools if tool.enabled],
                auth_required=False,
            )

        # ========== RAG知识库配置 ==========
        rag_config = None
        # 上下文携带rag_url，agent绑定了启用的知识库集合
        if context.rag_url and context.agent.collections:
            rag_config = RagConfig(
                rag_url=context.rag_url,
                collections=[binding.collection_id for binding in context.agent.collections if binding.enabled],
                project_id=context.project_id,
            )

        # ========== Workflow工作流配置 ==========
        workflow_config = None
        workflow_url = getattr(settings, "workflow_service_url", None)
        # 配置存在工作流服务地址，agent绑定启用的工作流
        if workflow_url and context.agent.workflows:
            workflow_config = WorkflowConfig(
                workflow_url=workflow_url,
                workflows=[str(binding.workflow_id) for binding in context.agent.workflows if binding.enabled],
                project_id=context.project_id,
            )

        # 拼装完整AgentConfig，给底层AgentBuilder使用
        return AgentConfig(
            model_name=context.agent.model,                     # LLM模型名称，来自数据库Agent
            temperature=config.get("temperature"),              # 温度，数据库存储
            max_tokens=config.get("max_tokens"),
            system_prompt=context.agent.instruction,           # Agent角色指令（数据库保存的专业指令集）
            system_message=context.system_message,              # 请求传入的临时系统提示，会覆盖/补充指令
            expected_output=context.expected_output or config.get("expected_output"), # 期望输出格式
            mcp_config=mcp_config,                              # MCP工具配置，没有就是None
            rag=rag_config,                                     # RAG知识库配置
            workflow=workflow_config,                           # 工作流配置
            enable_memory=context.enable_memory,                # 是否开启记忆，来自请求参数
            provider_credentials=context.agent.llm_provider_credentials, # LLM服务商密钥凭证
            markdown=config.get("markdown"),
            add_datetime_to_context=config.get("add_datetime_to_context"),
            add_location_to_context=config.get("add_location_to_context"),
            timezone_identifier=config.get("timezone_identifier"),
            tool_call_limit=config.get("tool_call_limit"),      # 单次agent最大工具调用次数限制
            num_history_runs=config.get("num_history_runs"),    # 读取多少条历史会话
            ui_mode=context.ui_mode,
        )