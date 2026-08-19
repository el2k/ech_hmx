"""Supervisor runtime service implemented via direct single‑agent execution."""
# Supervisor（调度器）运行时服务：负责**单个Agent的执行入口**
# 能力：普通同步调用、SSE流式输出、任务注册/取消、构建Agent执行上下文
# 底层依赖 AgnoAgentBuilder（构建Agent实例）、AgnoAgentRunner（真正跑Agent）

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Dict, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.exceptions import NotFoundError
from app.models.internal import AgentExecutionContext
from app.runtime.supervisor.agents.builder import AgnoAgentBuilder
from app.runtime.supervisor.agents.runner import AgnoAgentRunner
from app.runtime.supervisor.infrastructure.services import AIServiceClient
from app.runtime.supervisor.streaming.workflow_events import create_workflow_events
from app.runtime.tools.executor.service import ToolsRuntimeService
from app.schemas.agent_run import SupervisorRunRequest, SupervisorRunResponse
from app.services.agent_service import AgentService
from app.streaming.event_emitter import cleanup_event_emitter, get_event_emitter
from app.streaming.sse_handler import create_sse_response


@dataclass
class RunRegistryEntry:
    """Typed entry for a running single‑agent execution.
    正在运行Agent任务的注册表条目，内存中保存当前活跃任务信息，用于支持取消任务
    """
    runnable: object          # Agent可运行实例，上面会有cancel_run方法用于终止任务
    project_id: str           # 所属项目ID
    request_id: str           # 请求ID，日志链路追踪
    correlation_id: str       # 关联ID，流式事件链路标识
    execution_id: str         # 本次执行唯一ID，任务注销、取消的key
    agent_id: str             # Agent的id
    agent_name: str           # Agent名称，用于日志事件
    started_at: float         # 任务启动时间戳（unix时间）


class SupervisorRuntimeService:
    """High‑level facade coordinating direct single‑agent runtime execution.
    高层门面服务，协调单个Agent完整运行生命周期
    对外暴露3个核心方法：run(同步返回完整结果) / stream(SSE流式) / cancel(取消正在跑的Agent)
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],   # sqlalchemy异步会话工厂，用来创建db会话
        tools_runtime_service: ToolsRuntimeService,          # 工具运行时服务，Agent调用工具依赖它
    ) -> None:
        self._session_factory = session_factory
        self._tools_runtime = tools_runtime_service
        self._logger = get_logger("runtime.supervisor.service")

        # 从工具运行时拿到运行配置，传给Agent构建器
        runtime_settings = getattr(self._tools_runtime, "_settings", None)
        self._agent_builder = AgnoAgentBuilder(runtime_settings)   # Agent构建器：把请求、上下文组装成可运行Agent对象
        self._agent_runner = AgnoAgentRunner()                     # Agent执行器：真正执行Agent逻辑，同步/流式两套逻辑

        self._runs: Dict[str, RunRegistryEntry] = {}               # 内存任务注册表 key:execution_id，保存正在运行的agent任务
        self._runs_lock = asyncio.Lock()                           # 异步锁：并发读写_runs字典，防止多协程并发冲突

    async def run(
        self,
        payload: SupervisorRunRequest,
        project_id: uuid.UUID,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> SupervisorRunResponse:
        """Execute a single‑agent request and return the unified response.
        非流式接口：执行Agent，全部跑完之后一次性返回完整结果对象
        """
        # 组装内部鉴权、追踪请求头
        headers = self._build_auth_headers(project_id, extra_headers)

        try:
            # 构建Agent执行上下文对象，内部会解析agent_id、拉取agent数据库信息
            context, _ = await self._prepare_context(payload, project_id, headers)
            # 根据上下文，构建出完整可运行的Agent实例
            built_agent = await self._agent_builder.build_agent(context)

            self._logger.debug(
                "Starting supervisor run",
                agent_id=str(context.agent.id),
                request_id=context.request_id,
            )
            # 调用runner执行agent，等待全部执行完成返回统一响应结构体
            return await self._agent_runner.run(built_agent, context)

        except NotFoundError as exc:
            # 找不到agent、资源不存在，返回失败响应
            return self._build_failure_response(str(exc))
        except ValueError as exc:
            # 参数校验类错误
            return self._build_failure_response(str(exc))
        except Exception as exc:  # pragma: no cover - defensive runtime path
            # 兜底捕获所有未知异常，记录异常堆栈，返回统一失败报文，避免接口直接500
            self._logger.exception(
                "Supervisor run failed",
                project_id=str(project_id),
                request_id=headers.get("X‑Request‑ID"),
            )
            return self._build_failure_response(str(exc) or "Agent run failed")

    async def stream(
        self,
        payload: SupervisorRunRequest,
        project_id: uuid.UUID,
        extra_headers: Optional[Dict[str, str]] = None,
        http_request=None,
    ):
        """Execute a single‑agent request with Server‑Sent Events streaming.
        SSE流式执行Agent：返回SSE长连接，把Agent思考、工具调用、输出分段实时推给前端
        关键点：使用 asyncio.create_task 后台跑Agent业务，立刻返回SSE响应给客户端，不会阻塞http返回
        """
        if http_request is None:
            raise RuntimeError("HTTP request object required for streaming")

        auth_headers = self._build_auth_headers(project_id, extra_headers)
        request_id = auth_headers.get("X‑Request‑ID", str(uuid.uuid4()))
        correlation_id = str(uuid.uuid4())

        # 获取事件发射器，用来向外推送各类工作流事件（思考、调用工具、输出、报错）
        event_emitter = get_event_emitter(request_id, correlation_id)
        event_emitter.enable_streaming()
        # 封装工作流事件发送工具，比如发送workflow_started / agent_execution_started / workflow_failed
        workflow_events = create_workflow_events(event_emitter)

        async def coordination_task() -> None:
            """后台协程：真正执行Agent完整逻辑，运行在http请求之外的后台任务"""
            execution_id: Optional[str] = None
            try:
                # 1.准备执行上下文
                context, _ = await self._prepare_context(payload, project_id, auth_headers)
                # 推送事件：工作流已经开始
                workflow_events.emit_workflow_started(request_id, context)
                # 2.构建agent实例
                built_agent = await self._agent_builder.build_agent(context)
                execution_id = str(uuid.uuid4())

                # 3.注册任务到内存注册表，这样外部接口可以调用 /cancel 终止这个agent
                await self._register_run(
                    execution_id,
                    RunRegistryEntry(
                        runnable=built_agent.agent,
                        project_id=str(project_id),
                        request_id=request_id,
                        correlation_id=correlation_id,
                        execution_id=execution_id,
                        agent_id=str(context.agent.id),
                        agent_name=context.agent.name,
                        started_at=time.time(),
                    ),
                )
                # 推送事件：Agent正式开始执行
                workflow_events.emit_agent_execution_started(
                    agent_id=str(context.agent.id),
                    agent_name=context.agent.name,
                    execution_id=execution_id,
                    question=context.message,
                )
                # 4.执行流式Agent，执行过程中会源源不断通过workflow_events推送事件
                agent_result = await self._agent_runner.stream(
                    built_agent,
                    context,
                    workflow_events,
                    execution_id,
                )
                # 推送事件：整个工作流执行完成
                workflow_events.emit_workflow_completed(agent_result.total_time, 1)

            except ValueError as exc:
                workflow_events.emit_workflow_failed(str(exc), "agent_resolution")
            except NotFoundError as exc:
                workflow_events.emit_workflow_failed(str(exc), "agent_resolution")
            except Exception as exc:  # pragma: no cover - streaming error path
                self._logger.exception(
                    "Agent workflow failed during streaming",
                    request_id=request_id,
                    correlation_id=correlation_id,
                )
                workflow_events.emit_workflow_failed(str(exc), "agent_execution")
            finally:
                # 无论成功失败，必须清理：注销内存任务、销毁事件发射器，防止内存泄漏
                if execution_id is not None:
                    await self._unregister_run(execution_id)
                cleanup_event_emitter(request_id, correlation_id)

        # ⭐重点：创建后台协程，立刻返回SSE响应，Agent逻辑在后台跑，http连接保持推送事件
        asyncio.create_task(coordination_task())
        return create_sse_response(event_emitter, http_request)

    async def cancel(self, run_id: str, project_id: uuid.UUID, reason: Optional[str] = None) -> bool:
        """Cancel a running single‑agent execution by run_id.
        根据execution_id取消正在运行的Agent任务
        返回True代表成功触发取消；False代表任务不存在/无权取消/agent不支持取消
        """
        # 加锁读取内存注册表
        async with self._runs_lock:
            entry = self._runs.get(run_id)

        if entry is None:
            self._logger.info("Cancel requested for unknown run_id", run_id=run_id)
            return False
        # 权限校验：不能跨项目取消别人的Agent任务
        if str(project_id) != entry.project_id:
            self._logger.warning(
                "Cancel forbidden: project mismatch",
                run_id=run_id,
                expected_project_id=entry.project_id,
                got_project_id=str(project_id),
            )
            return False

        # 判断agent实例是否具备cancel_run取消方法，有些agent不支持中断
        cancel_run = getattr(entry.runnable, "cancel_run", None)
        if not callable(cancel_run):
            self._logger.warning(
                "Cancel unsupported for running agent",
                run_id=run_id,
                agent_id=entry.agent_id,
            )
            return False

        try:
            cancel_run(run_id)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.exception("Cancel request failed", run_id=run_id, error=str(exc))
            return False

    async def _register_run(self, run_id: str, entry: RunRegistryEntry) -> None:
        """注册运行中的agent任务到内存字典，加异步锁保证并发安全"""
        async with self._runs_lock:
            self._runs[run_id] = entry
            self._logger.debug(
                "Registered running agent execution",
                run_id=run_id,
                agent_id=entry.agent_id,
                request_id=entry.request_id,
            )

    async def _unregister_run(self, run_id: str) -> None:
        """任务结束后，从内存注册表删除，释放内存"""
        async with self._runs_lock:
            entry = self._runs.pop(run_id, None)
        if entry is not None:
            self._logger.debug(
                "Unregistered agent execution",
                run_id=run_id,
                agent_id=entry.agent_id,
                request_id=entry.request_id,
            )

    async def _prepare_context(
        self,
        payload: SupervisorRunRequest,
        project_id: uuid.UUID,
        headers: Dict[str, str],
    ) -> Tuple[AgentExecutionContext, str]:
        """构建Agent执行上下文AgentExecutionContext
        1.解析agent_id（请求不传就取项目默认agent）
        2.数据库读取agent完整配置
        3.组装所有运行参数，生成上下文对象，给builder/runner使用
        """
        async with self._agent_service_context() as agent_service:
            # 解析得到真正agent_id
            agent_id = await self._resolve_agent_id(payload, project_id, agent_service)
            # 通过AIServiceClient拉取数据库中agent完整配置信息
            async with AIServiceClient(agent_service, project_id) as ai_client:
                agent = await ai_client.get_agent(agent_id, headers)

        # 组装完整执行上下文，所有后面Agent运行需要的参数全部放这里
        context = AgentExecutionContext(
            agent=agent,
            project_id=str(project_id),
            message=payload.message,
            system_message=payload.system_message,
            expected_output=payload.expected_output,
            session_id=payload.session_id,
            user_id=payload.user_id,
            request_id=headers["X‑Request‑ID"],
            timeout=payload.timeout,
            mcp_url=payload.mcp_url,
            rag_url=payload.rag_url,
            enable_memory=payload.enable_memory,
        )
        return context, agent_id

    @asynccontextmanager
    async def _agent_service_context(self) -> AsyncIterator[AgentService]:
        """异步上下文管理器：创建数据库会话，生成AgentService
        自动处理会话：异常回滚、事务回滚、关闭db连接，避免连接泄露
        """
        session: AsyncSession = self._session_factory()
        try:
            yield AgentService(session)
        except Exception:
            # 如果发生异常，事务没提交就回滚
            if session.in_transaction():
                await session.rollback()
            raise
        else:
            # 正常流程，如果还存在事务，也做回滚，本场景只做查询，不写库
            if session.in_transaction():
                await session.rollback()
        finally:
            await session.close()

    async def _resolve_agent_id(
        self,
        payload: SupervisorRunRequest,
        project_id: uuid.UUID,
        agent_service: AgentService,
    ) -> str:
        """解析agent_id：请求参数携带agent_id就直接用；没有就读取项目设置的默认Agent"""
        if payload.agent_id:
            return str(payload.agent_id)

        try:
            default_agent = await agent_service.get_default_agent(project_id)
        except NotFoundError as exc:
            raise ValueError("Default agent not configured for project") from exc
        return str(default_agent.id)

    @staticmethod
    def _build_auth_headers(project_id: uuid.UUID, extra_headers: Optional[Dict[str, str]]) -> Dict[str, str]:
        """组装内部请求头：X‑Project‑ID、X‑Request‑ID链路追踪ID，合并外部额外header"""
        headers = dict(extra_headers or {})
        headers.setdefault("X‑Project‑ID", str(project_id))
        headers.setdefault("X‑Request‑ID", str(uuid.uuid4()))
        return headers

    @staticmethod
    def _build_failure_response(message: str) -> SupervisorRunResponse:
        """静态工具：构造统一失败返回结构体，同步run接口出错时使用"""
        return SupervisorRunResponse(
            success=False,
            message=message,
            result=None,
            content="",
            metadata=None,
            error=message,
        )