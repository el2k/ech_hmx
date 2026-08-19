"""Run direct single-agent supervisor executions."""
# 直接执行单智能体 Supervisor 运行逻辑

from __future__ import annotations
# 启用延迟注解求值，支持类内部注解引用自身类型（Python 3.7+特性）

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

# 导入 Agno 框架智能体运行时事件模型：流式运行会抛出这些事件对象
from agno.agent import (
    RunCancelledEvent,        # 运行被取消事件
    RunCompletedEvent,        # 运行正常完成事件
    RunContentEvent,          # 内容分片输出事件（流式token）
    RunErrorEvent,            # 运行异常报错事件
    ToolCallCompletedEvent,   # 工具调用完成事件
    ToolCallStartedEvent,     # 工具调用开始事件
)

# 项目内部模块导入
from app.core.logging import get_logger                          # 日志工厂函数
from app.models.internal import AgentExecutionContext           # 智能体执行上下文，携带会话、用户、消息、agent实例信息
from app.runtime.supervisor.streaming.workflow_events import WorkflowEventEmitter  # 工作流事件发射器，向外推送流式事件
from app.schemas.agent_run import AgentExecutionResult, AgentRunMetadata, SupervisorRunResponse  # Pydantic输出响应结构体

from .builder import BuiltAgent  # 构建完成的Agent包装对象，封装agno原始agent实例


@dataclass
class AgentRunResult:
    """Container for final single-agent execution artifacts.
    数据类：保存单智能体执行结束后的原始输出产物，供上层Supervisor使用
    """
    content: str                # 智能体最终输出文本
    total_time: float           # 执行总耗时（秒）
    success: bool               # 是否执行成功
    error: Optional[str] = None # 错误信息，失败时填充，成功为None


class AgnoAgentRunner:
    """Execute a direct Agno agent with single-agent response semantics.
    封装 Agno Agent 的执行器，提供两种模式：
    1. run()：非流式调用，一次性返回完整响应
    2. stream()：流式调用，消费Agno事件流，向外发射工作流事件
    """

    def __init__(self) -> None:
        # 初始化本运行器专属logger，标记模块路径便于日志检索
        self._logger = get_logger("runtime.supervisor.agents.runner")

    async def run(self, built_agent: BuiltAgent, context: AgentExecutionContext) -> SupervisorRunResponse:
        """Run a single agent and translate the result into the public response schema.
        非流式执行单个智能体，把Agno原始输出转换为对外接口响应结构体
        :param built_agent: 已经配置构建完毕的Agent包装实例
        :param context: 智能体执行上下文（消息、session_id、user_id、agent元数据）
        :return: SupervisorRunResponse 对外API返回的标准化响应对象
        """
        start_time = time.time()  # 记录开始时间戳
        # 调用agno异步arun，关闭流式输出；传入用户消息、会话、用户标识
        output = await built_agent.agent.arun(
            context.message,
            stream=False,
            session_id=context.session_id,
            user_id=context.user_id,
        )
        total_time = time.time() - start_time  # 计算总执行耗时

        # 安全提取输出内容，兼容content为None的边界情况
        final_content = self._ensure_text(getattr(output, "content", None))
        # 提取本次执行调用过的全部工具名称列表
        tools_used = self._extract_tool_names(getattr(output, "tools", None))

        # 组装执行结果对象
        result = AgentExecutionResult(
            agent_id=context.agent.id,
            agent_name=context.agent.name,
            question=context.message,
            content=final_content,
            tools_used=tools_used or None,
            execution_time=total_time,
            success=True,
            error=None,
        )
        # 组装运行元数据
        metadata = AgentRunMetadata(
            agent_id=context.agent.id,
            agent_name=context.agent.name,
            total_execution_time=total_time,
            session_id=context.session_id,
        )
        # 返回标准化对外响应
        return SupervisorRunResponse(
            success=True,
            message="Agent run completed",
            result=result,
            content=final_content,
            metadata=metadata,
            error=None,
        )

    async def stream(
        self,
        built_agent: BuiltAgent,
        context: AgentExecutionContext,
        workflow_events: WorkflowEventEmitter,
        execution_id: str,
    ) -> AgentRunResult:
        """Run a single agent with streaming workflow events.
        流式运行智能体，消费Agno产出的事件流，通过WorkflowEventEmitter向外推送事件；
        收集所有分片，执行结束返回内部AgentRunResult对象给上层Supervisor。
        :param built_agent: 构建好的agent包装实例
        :param context: 执行上下文
        :param workflow_events: 事件发射器，对外发送流式事件（例如websocket）
        :param execution_id: 本次agent执行唯一ID，用于事件追踪
        :return: AgentRunResult 聚合后的完整运行结果
        """
        start_time = time.time()
        content_chunks: list[str] = []  # 缓存所有输出文本分片，最后拼接完整结果
        success = True                  # 运行状态标记，默认成功
        error: Optional[str] = None     # 错误信息
        chunk_index = 0                 # 分片序号，用于流式事件标记分片顺序
        tool_calls = 0                  # 统计本次agent调用工具总次数

        # 开启agno流式运行，stream_intermediate_steps=True 会输出工具调用等中间步骤事件
        async for event in built_agent.agent.arun(
            context.message,
            stream=True,
            stream_intermediate_steps=True,
            session_id=context.session_id,
            user_id=context.user_id,
        ):
            timestamp = datetime.now(timezone.utc).isoformat()  # UTC标准时间戳字符串

            # ---------------------- 内容分片事件：模型输出token片段 ----------------------
            if isinstance(event, RunContentEvent):
                content = event.content or ""
                if content:
                    content_chunks.append(content)
                    # 向外发射agent内容分片事件，is_final=False代表不是结束分片
                    workflow_events.emit_agent_content_chunk(
                        agent_id=str(context.agent.id),
                        agent_name=context.agent.name,
                        execution_id=execution_id,
                        content_chunk=content,
                        chunk_index=chunk_index,
                        is_final=False,
                    )
                    chunk_index += 1
                continue

            # ---------------------- 工具调用开始事件 ----------------------
            if isinstance(event, ToolCallStartedEvent) and event.tool:
                tool_calls += 1
                workflow_events.emit_agent_tool_call_started(
                    agent_id=str(context.agent.id),
                    agent_name=context.agent.name,
                    execution_id=execution_id,
                    tool_name=getattr(event.tool, "tool_name", "unknown_tool"),
                    tool_call_id=getattr(event.tool, "tool_call_id", None),
                    tool_input=getattr(event.tool, "tool_args", None),
                )
                continue

            # ---------------------- 工具调用完成事件 ----------------------
            if isinstance(event, ToolCallCompletedEvent) and event.tool:
                workflow_events.emit_agent_tool_call_completed(
                    agent_id=str(context.agent.id),
                    agent_name=context.agent.name,
                    execution_id=execution_id,
                    tool_name=getattr(event.tool, "tool_name", "unknown_tool"),
                    tool_call_id=getattr(event.tool, "tool_call_id", None),
                    tool_input=getattr(event.tool, "tool_args", None),
                    tool_output=getattr(event.tool, "result", None),
                )
                continue

            # ---------------------- Agent运行正常完成事件 ----------------------
            if isinstance(event, RunCompletedEvent):
                final_content = self._ensure_text(getattr(event, "content", None))
                if final_content:
                    content_chunks.append(final_content)
                continue

            # ---------------------- Agent运行报错事件 ----------------------
            if isinstance(event, RunErrorEvent):
                success = False
                error = event.content or event.error_type or "Agent run failed"
                self._logger.error(
                    "Agent streaming run failed",
                    agent_id=str(context.agent.id),
                    request_id=context.request_id,
                    timestamp=timestamp,
                    error=error,
                )
                continue

            # ---------------------- Agent运行被取消事件（用户/系统中断） ----------------------
            if isinstance(event, RunCancelledEvent):
                success = False
                error = event.reason or "Agent run cancelled"
                self._logger.info(
                    "Agent streaming run cancelled",
                    agent_id=str(context.agent.id),
                    request_id=context.request_id,
                    timestamp=timestamp,
                    error=error,
                )

        # 循环结束：把所有文本分片拼接成完整回答
        final_content = "".join(content_chunks)
        # 向外发送agent执行完毕事件，携带统计信息
        workflow_events.emit_agent_response_complete(
            agent_id=str(context.agent.id),
            agent_name=context.agent.name,
            execution_id=execution_id,
            final_content=final_content,
            success=success,
            total_chunks=len(content_chunks),
            tool_calls_count=tool_calls,
        )
        # 返回聚合后的内部结果对象给上层Supervisor工作流
        return AgentRunResult(
            content=final_content,
            total_time=time.time() - start_time,
            success=success,
            error=error,
        )

    @staticmethod
    def _ensure_text(value: Optional[Any]) -> str:
        """
        静态工具方法：安全转为字符串，处理None、非字符串类型
        :param value: 任意对象，可能为None
        :return: 纯字符串，None返回空字符串
        """
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    @staticmethod
    def _extract_tool_names(tools: Any) -> list[str]:
        """
        静态工具方法：从工具对象列表提取工具名称字符串
        :param tools: agno返回的工具对象列表，可能为None
        :return: 工具名称字符串列表
        """
        if not tools:
            return []

        names: list[str] = []
        for tool in tools:
            name = getattr(tool, "tool_name", None)
            if isinstance(name, str) and name:
                names.append(name)
        return names