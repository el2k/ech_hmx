# =============================================================================
# 模块：会话超时关闭定时任务 (Periodic task to close timed-out sessions)
# =============================================================================
# 该模块提供了定期检查和关闭超时会话的功能，主要包括：
# 1. 定期扫描超时的开放会话
# 2. 按项目配置的超时时间关闭会话
# 3. 调用 session_service.close_visitor_session 执行实际关闭
# 4. 支持手动触发超时检查
# 
# 设计目的：
# - 防止客服或访客忘记关闭会话导致资源泄漏
# - 释放客服的并发槽位，让更多访客可以得到服务
# - 提升系统的资源利用率和公平性
# =============================================================================

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models import VisitorSession, SessionStatus, VisitorAssignmentRule
from app.services.session_service import close_visitor_session

logger = get_logger("tasks.close_timeout_sessions")

# =============================================================================
# 全局状态变量（用于任务生命周期管理和并发控制）
# =============================================================================
_task: Optional[asyncio.Task] = None          # 后台任务的句柄
_processing_lock = asyncio.Lock()             # 防止并发执行超时检查的锁


# =============================================================================
# 辅助函数：获取项目超时配置
# =============================================================================

def _get_project_timeout_hours(db: Session, project_id: UUID, cache: Dict[UUID, int]) -> int:
    """
    获取项目的会话超时时间（小时）。

    优先级：
    1. 如果项目配置了 VisitorAssignmentRule.auto_close_hours，使用该值
    2. 否则使用全局配置 SESSION_DEFAULT_TIMEOUT_HOURS

    使用缓存避免每次检查都查询数据库，提升性能。

    Args:
        db: 数据库会话
        project_id: 项目ID
        cache: 超时时间缓存字典 {project_id: timeout_hours}

    Returns:
        int: 超时时间（小时）
    """
    # 如果已缓存，直接返回
    if project_id in cache:
        return cache[project_id]

    # 查询项目的分配规则
    rule = db.query(VisitorAssignmentRule).filter(
        VisitorAssignmentRule.project_id == project_id
    ).first()

    # 使用项目配置或全局默认值
    if rule and rule.auto_close_hours:
        timeout_hours = rule.auto_close_hours
    else:
        timeout_hours = settings.SESSION_DEFAULT_TIMEOUT_HOURS

    # 缓存结果
    cache[project_id] = timeout_hours
    return timeout_hours


# =============================================================================
# 核心处理函数
# =============================================================================

async def _process_timeout_sessions() -> int:
    """
    处理并关闭超时的会话。

    执行流程：
    1. 查询所有可能超时的开放会话（基于全局最小超时时间）
    2. 对每个会话，检查其项目特定的超时时间
    3. 如果会话确实超时，调用 close_visitor_session 关闭
    4. 统计并返回关闭的会话数量

    设计考量：
    - 使用批量限制（SESSION_TIMEOUT_BATCH_SIZE）防止一次处理过多
    - 先使用全局最小超时时间筛选候选，再逐个项目检查
    - 使用 joinedload 预加载 visitor 关系，避免 N+1 查询
    - 每个会话独立处理，失败不影响其他会话

    Returns:
        int: 成功关闭的会话数量
    """
    db: Session = SessionLocal()
    closed_count = 0
    timeout_cache: Dict[UUID, int] = {}  # project_id -> timeout_hours 缓存

    try:
        # =====================================================================
        # 步骤1: 查询可能超时的会话
        # =====================================================================
        # 先使用全局最小超时时间筛选候选，减少查询范围
        # 后续再对每个会话进行项目特定的精确检查
        min_timeout_hours = settings.SESSION_DEFAULT_TIMEOUT_HOURS
        cutoff_time = datetime.utcnow() - timedelta(hours=min_timeout_hours)

        # 查询开放会话中 updated_at 早于截止时间的
        # 使用 joinedload 预加载 visitor 关系，避免后续查询
        sessions = (
            db.query(VisitorSession)
            .filter(
                VisitorSession.status == SessionStatus.OPEN.value,
                # 会话最近更新时间早于截止时间（表示可能不活跃）
                VisitorSession.updated_at < cutoff_time,
            )
            .options(joinedload(VisitorSession.visitor))
            .limit(settings.SESSION_TIMEOUT_BATCH_SIZE)  # 限制批次大小
            .all()
        )

        if not sessions:
            logger.debug("No potentially timed-out sessions found")
            return 0

        logger.info(f"Found {len(sessions)} potentially timed-out sessions to check")

        # =====================================================================
        # 步骤2: 逐个检查并关闭超时会话
        # =====================================================================
        for session in sessions:
            try:
                # 2a: 获取项目特定的超时时间
                timeout_hours = _get_project_timeout_hours(
                    db, session.project_id, timeout_cache
                )

                # 2b: 计算该项目特定的截止时间
                project_cutoff = datetime.utcnow() - timedelta(hours=timeout_hours)

                # 2c: 确定最后活动时间
                # 优先使用 last_message_at（最后消息时间），否则使用 updated_at
                last_activity = session.last_message_at or session.updated_at

                # 2d: 检查会话是否真正超时
                if last_activity >= project_cutoff:
                    logger.debug(
                        f"Session {session.id} not yet timed out "
                        f"(last_activity={last_activity}, cutoff={project_cutoff})"
                    )
                    continue

                # 2e: 关闭超时会话
                logger.info(
                    f"Closing timed-out session {session.id}",
                    extra={
                        "session_id": str(session.id),
                        "visitor_id": str(session.visitor_id),
                        "project_id": str(session.project_id),
                        "last_activity": str(last_activity),
                        "timeout_hours": timeout_hours,
                    }
                )

                # 调用会话服务关闭会话
                # closed_by_staff=None 表示由系统自动关闭
                await close_visitor_session(
                    db=db,
                    session=session,
                    closed_by_staff=None,  # 系统自动关闭
                    send_notification=True,  # 向访客发送通知
                    auto_commit=True,
                    reason=f"timeout ({timeout_hours}h inactivity)",
                )

                closed_count += 1

            except ValueError as e:
                # 会话已经被关闭（可能是其他进程关闭的）
                logger.debug(f"Session {session.id} already closed: {e}")
            except Exception as e:
                # 记录错误但继续处理其他会话
                logger.error(
                    f"Failed to close timed-out session {session.id}: {e}",
                    extra={"session_id": str(session.id), "error": str(e)},
                )

        logger.info(f"Closed {closed_count} timed-out sessions")
        return closed_count

    except Exception as e:
        logger.error(f"Error processing timeout sessions: {e}")
        return closed_count
    finally:
        db.close()


# =============================================================================
# 定时任务循环
# =============================================================================

async def _run_periodic_task():
    """
    运行周期性的会话超时检查任务。

    这是一个无限循环，按照配置的间隔不断执行超时检查。
    使用锁防止在任务执行期间再次触发。
    """
    logger.info(
        f"Starting session timeout check task "
        f"(interval={settings.SESSION_TIMEOUT_CHECK_INTERVAL_SECONDS}s, "
        f"default_timeout={settings.SESSION_DEFAULT_TIMEOUT_HOURS}h)"
    )

    while True:
        try:
            # 使用锁防止并发执行
            async with _processing_lock:
                closed_count = await _process_timeout_sessions()
                if closed_count > 0:
                    logger.info(f"Periodic check: closed {closed_count} timed-out sessions")
        except Exception as e:
            logger.error(f"Error in periodic session timeout check: {e}")

        # 等待下一个检查周期
        await asyncio.sleep(settings.SESSION_TIMEOUT_CHECK_INTERVAL_SECONDS)


# =============================================================================
# 任务生命周期管理
# =============================================================================

async def start_session_timeout_task():
    """
    启动后台会话超时检查任务。

    在应用启动时调用此函数来启动定时任务。
    如果任务已禁用或已在运行，则相应处理。
    """
    global _task

    # 检查是否启用了超时检查
    if not settings.SESSION_TIMEOUT_CHECK_ENABLED:
        logger.info("Session timeout check is disabled")
        return

    # 检查任务是否已在运行
    if _task is not None and not _task.done():
        logger.warning("Session timeout check task is already running")
        return

    # 创建并启动异步任务
    _task = asyncio.create_task(_run_periodic_task())
    logger.info("Session timeout check task started")


async def stop_session_timeout_task():
    """
    停止后台会话超时检查任务。

    在应用关闭时调用此函数来优雅地停止定时任务。
    """
    global _task

    if _task is None:
        return

    # 取消任务
    _task.cancel()
    try:
        # 等待任务被取消（会抛出 CancelledError）
        await _task
    except asyncio.CancelledError:
        pass  # 任务被正常取消

    _task = None
    logger.info("Session timeout check task stopped")


# =============================================================================
# 手动触发接口
# =============================================================================

async def trigger_timeout_check() -> int:
    """
    手动触发的会话超时检查。

    可从 API 端点调用，用于需要立即处理超时会话的场景。
    例如：管理员手动触发、测试场景、或系统启动后的首次检查。

    使用锁确保与定时任务不并发执行。

    Returns:
        int: 成功关闭的会话数量
    """
    async with _processing_lock:
        return await _process_timeout_sessions()