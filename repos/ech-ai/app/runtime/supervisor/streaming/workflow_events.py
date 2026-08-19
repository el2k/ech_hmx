"""Workflow event generation for the single-agent supervisor runtime."""
# 单智能体 Supervisor 运行时：工作流事件生成模块
# 职责：封装所有工作流/Agent流式事件，组装标准化事件数据，调用底层发射器向外推送事件

from __future__ import annotations
# 延迟类型注解，支持类内部引用自身类型

from typing import Any, Dict, Optional

# 内部模型：Agent执行上下文，保存会话、用户、Agent元信息
from app.models.internal import AgentExecutionContext
# 流式事件数据模型：Pydantic数据结构体，定义每种事件携带的数据字段
from app.models.streaming import (
    AgentContentChunkData,        # Agent文本分片事件数据
    AgentExecutionData,           # Agent开始执行事件数据
    AgentResponseCompleteData,    # Agent完整响应结束事件数据
    AgentToolCallData,            # Agent工具调用（开始/完成）事件数据
    ErrorEventData,               # 错误事件数据
    EventSeverity,                # 事件严重等级枚举：INFO / SUCCESS / ERROR
    EventType,                    # 事件类型枚举，定义全部事件标识符
    JsonRenderUpdateData,         # JSON动态渲染更新事件数据
    ProgressUpdateData,           # 工作流进度更新事件数据
    WorkflowStartedData,          # 工作流启动事件数据
)
# 底层流式事件发射器：实际完成消息发送（一般是WebSocket/SSE推送）
from app.streaming.event_emitter import StreamingEventEmitter


class WorkflowEventEmitter:
    """Event emitter for direct single‑agent workflow progress.
    单Agent工作流事件发射器
    包装底层 StreamingEventEmitter，对上层业务提供语义化的事件发送方法；
    上层runner只需要调用 emit_xxx，不用关心EventType、数据模型、metadata组装。
    """

    def __init__(self, event_emitter: StreamingEventEmitter):
        # 注入底层原始事件发射器，真正负责网络层消息下发
        self.emitter = event_emitter

    def emit_workflow_started(self, request_id: str, context: AgentExecutionContext) -> None:
        """Emit workflow started event.
        发送【工作流开始】事件：整个Supervisor会话启动
        :param request_id: 请求全局唯一ID
        :param context: Agent执行上下文对象
        """
        # 组装事件业务数据
        data = WorkflowStartedData(
            request_id=request_id,
            agent_id=str(context.agent.id),
            agent_name=context.agent.name,
            session_id=context.session_id,
            message_length=len(context.message),
        )
        # 元数据：用于日志、前端过滤、链路追踪
        metadata = {
            "phase": "initialization",
            "agent_id": str(context.agent.id),
        }
        # 会话ID存在则追加进metadata
        if context.session_id:
            metadata["session_id"] = context.session_id

        # 调用底层发射器发送事件：事件类型、业务数据、事件级别、追踪元数据
        self.emitter.emit(EventType.WORKFLOW_STARTED, data, EventSeverity.INFO, metadata)

    def emit_workflow_completed(self, total_time: float, agents_consulted: int) -> None:
        """Emit workflow completed event.
        发送【工作流全部完成】事件，代表Supervisor整个流程结束
        :param total_time: 整体工作流耗时，单位秒
        :param agents_consulted: 本次工作流一共调用过多少个Agent
        """
        data = ProgressUpdateData(
            phase="completed",
            progress_percentage=100.0,        # 进度100%
            current_step="Workflow completed",
            total_steps=3,                    # 预设总步骤数
            completed_steps=3,               # 全部步骤完成
        )
        self.emitter.emit(
            EventType.WORKFLOW_COMPLETED,
            data,
            EventSeverity.SUCCESS,
            {
                "total_execution_time": total_time,
                "agents_consulted": agents_consulted,
            },
        )

    def emit_workflow_failed(self, error: str, component: str) -> None:
        """Emit workflow failed event.
        发送【工作流整体失败】事件，整个Supervisor流程异常终止
        :param error: 错误描述文本
        :param component: 出错组件名称，用于定位哪里报错（runner / builder / llm等）
        """
        data = ErrorEventData(
            error_type="WorkflowError",
            error_message=error,
            component=component,
        )
        self.emitter.emit(
            EventType.WORKFLOW_FAILED,
            data,
            EventSeverity.ERROR,
            {"phase": "error"},
        )

    def emit_agent_execution_started(
        self,
        agent_id: str,
        agent_name: str,
        execution_id: str,
        question: str,
    ) -> None:
        """Emit agent execution started event.
        发送【单个Agent开始执行】事件，标记某个Agent正式开始跑
        :param agent_id: Agent唯一ID
        :param agent_name: Agent名称
        :param execution_id: 本次Agent执行实例ID（区分同一个Agent多次调用）
        :param question: 给到该Agent的输入问题/指令
        """
        data = AgentExecutionData(
            agent_id=agent_id,
            agent_name=agent_name,
            execution_id=execution_id,
            question=question,
        )
        self.emitter.emit(
            EventType.AGENT_EXECUTION_STARTED,
            data,
            EventSeverity.INFO,
            {"phase": "execution", "agent_id": agent_id},
        )

    def emit_agent_content_chunk(
        self,
        agent_id: str,
        agent_name: str,
        execution_id: str,
        content_chunk: str,
        chunk_index: int,
        is_final: bool = False,
        agent_role: Optional[str] = None,
    ) -> None:
        """Emit agent content chunk event.
        发送【Agent文本分片】事件，流式输出token片段，前端拼接展示回答
        :param agent_id: Agent ID
        :param agent_name: Agent名称
        :param execution_id: Agent执行ID
        :param content_chunk: 当前输出文本片段
        :param chunk_index: 分片序号，前端可用于排序、去重
        :param is_final: 是否是最后一块分片
        :param agent_role: Agent角色标记（可选）
        """
        data = AgentContentChunkData(
            agent_id=agent_id,
            agent_name=agent_name,
            execution_id=execution_id,
            content_chunk=content_chunk,
            chunk_index=chunk_index,
            is_final=is_final,
            agent_role=agent_role,
        )
        self.emitter.emit(
            EventType.AGENT_CONTENT_CHUNK,
            data,
            EventSeverity.INFO,
            {"phase": "agent_execution", "agent_id": agent_id},
        )

    def emit_agent_tool_call_started(
        self,
        agent_id: str,
        agent_name: str,
        execution_id: str,
        tool_name: str,
        tool_call_id: Optional[str] = None,
        tool_input: Optional[dict] = None,
    ) -> None:
        """Emit agent tool call started event.
        发送【工具调用开始】事件：Agent准备调用工具
        :param agent_id: Agent ID
        :param agent_name: Agent名称
        :param execution_id: Agent执行ID
        :param tool_name: 工具函数名
        :param tool_call_id: LLM生成的工具调用唯一ID
        :param tool_input: 传给工具的入参字典
        """
        data = AgentToolCallData(
            agent_id=agent_id,
            agent_name=agent_name,
            execution_id=execution_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
            status="started",  # 标记工具状态：已启动
        )
        self.emitter.emit(
            EventType.AGENT_TOOL_CALL_STARTED,
            data,
            EventSeverity.INFO,
            {
                "phase": "agent_execution",
                "agent_id": agent_id,
                "tool_name": tool_name,
            },
        )

    def emit_agent_tool_call_completed(
        self,
        agent_id: str,
        agent_name: str,
        execution_id: str,
        tool_name: str,
        tool_call_id: Optional[str] = None,
        tool_input: Optional[dict] = None,
        tool_output: Optional[str] = None,
    ) -> None:
        """Emit agent tool call completed event.
        发送【工具调用完成】事件：工具执行完毕，带回输出结果
        """
        data = AgentToolCallData(
            agent_id=agent_id,
            agent_name=agent_name,
            execution_id=execution_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_input=tool_input,
            tool_output=tool_output,
            status="completed", # 标记工具状态：执行完成
        )
        self.emitter.emit(
            EventType.AGENT_TOOL_CALL_COMPLETED,
            data,
            EventSeverity.SUCCESS,
            {
                "phase": "agent_execution",
                "agent_id": agent_id,
                "tool_name": tool_name,
            },
        )

    def emit_agent_response_complete(
        self,
        agent_id: str,
        agent_name: str,
        execution_id: str,
        final_content: str,
        success: bool,
        total_chunks: int,
        tool_calls_count: int = 0,
    ) -> None:
        """Emit final agent response event.
        发送【Agent执行结束】事件，单个Agent全部输出完成，携带完整结果与统计
        :param agent_id: Agent ID
        :param agent_name: Agent名称
        :param execution_id: Agent执行ID
        :param final_content: Agent完整回答文本
        :param success: 本次Agent是否运行成功
        :param total_chunks: 本次一共输出多少个文本分片
        :param tool_calls_count: 本次Agent调用工具总次数
        """
        data = AgentResponseCompleteData(
            agent_id=agent_id,
            agent_name=agent_name,
            execution_id=execution_id,
            final_content=final_content,
            success=success,
            total_chunks=total_chunks,
            tool_calls_count=tool_calls_count,
            response_length=len(final_content), # 统计回答字符长度
        )
        # 根据运行成功/失败切换事件严重等级
        severity = EventSeverity.SUCCESS if success else EventSeverity.ERROR
        self.emitter.emit(
            EventType.AGENT_RESPONSE_COMPLETE,
            data,
            severity,
            {"phase": "agent_execution", "agent_id": agent_id},
        )

    def emit_json_render_update(
        self,
        *,
        patches: list[Dict[str, Any]],
        text_content: Optional[str] = None,
        member_id: Optional[str] = None,
    ) -> None:
        """Emit a json‑render update event carrying SpecStream patch lines.
        发送JSON动态渲染更新事件；关键字-only参数
        用于流式增量JSON输出，前端基于patches做局部JSON打补丁更新
        :param patches: SpecStream增量补丁数组
        :param text_content: 附带文本内容（可选）
        :param member_id: 成员标识（可选）
        """
        data = JsonRenderUpdateData(patches=patches, text_content=text_content)
        metadata: Dict[str, Any] = {"phase": "json_render"}
        if member_id:
            metadata["member_id"] = member_id
        self.emitter.emit(EventType.JSON_RENDER_UPDATE, data, EventSeverity.INFO, metadata)


def create_workflow_events(event_emitter: StreamingEventEmitter) -> WorkflowEventEmitter:
    """Create a workflow event emitter.
    工厂函数：创建WorkflowEventEmitter实例
    :param event_emitter: 底层原始事件发射器
    :return: 封装好的工作流事件发射器对象
    """
    return WorkflowEventEmitter(event_emitter)