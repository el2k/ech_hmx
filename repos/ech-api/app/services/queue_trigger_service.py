# =============================================================================
# 模块：队列触发服务 (Queue trigger service)
# =============================================================================
# 该模块提供了事件驱动的队列处理触发功能，用于在以下场景主动处理等待队列：
# 1. 客服变为可用状态（恢复服务、上线、结束会话）
# 2. 访客进入队列（立即尝试分配）
# 
# 与 fallback 处理（低频轮询）不同，本模块是事件驱动的，响应更快。
# =============================================================================

from __future__ import annotations

import asyncio
from typing import List, Optional, Set
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models import (
    Staff,
    StaffRole,
    VisitorAssignmentRule,
    VisitorSession,
    SessionStatus,
    VisitorWaitingQueue,
    WaitingStatus,
)

logger = get_logger("services.queue_trigger")

# =============================================================================
# 全局状态变量（用于并发控制）
# =============================================================================
_processing_lock = asyncio.Lock()               # 保护 _processing_project_ids 集合的锁
_processing_project_ids: Set[UUID] = set()      # 正在处理队列的项目ID集合（防止同一项目重复处理）
_semaphore: Optional[asyncio.Semaphore] = None  # 控制并发处理数量的信号量


def _get_semaphore() -> asyncio.Semaphore:
    """
    获取或创建用于控制并发处理数量的信号量。
    信号量的最大值由配置项 QUEUE_PROCESS_MAX_WORKERS 决定。
    """
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.QUEUE_PROCESS_MAX_WORKERS)
    return _semaphore


# =============================================================================
# 项目级队列触发
# =============================================================================

async def trigger_queue_for_project(project_id: UUID) -> None:
    """
    触发特定项目的队列处理。

    当项目中有客服变为可用时调用此函数：
    - 客服恢复服务 (service_paused = False)
    - 客服激活服务 (is_active = True)
    - 客服会话关闭（释放了一个并发槽位）

    设计考量：
    - 使用锁防止同一项目被多次触发导致并发冲突
    - 实际处理在后台异步执行，不阻塞调用方
    - 如果项目已在处理中，直接返回避免重复

    Args:
        project_id: 需要处理队列的项目ID
    """
    # 检查该项目是否已经在处理中
    async with _processing_lock:
        if project_id in _processing_project_ids:
            logger.debug(f"Project {project_id} queue is already being processed")
            return
        # 标记该项目为正在处理
        _processing_project_ids.add(project_id)

    try:
        # 在后台异步处理队列（不等待完成）
        asyncio.create_task(_process_project_queue_internal(project_id))
    except Exception as e:
        logger.error(f"Failed to trigger queue processing for project {project_id}: {e}")
        # 发生异常时，从处理集合中移除标记
        async with _processing_lock:
            _processing_project_ids.discard(project_id)


async def trigger_queue_for_staff(staff_id: UUID, project_id: UUID) -> None:
    """
    当特定客服变为可用时触发队列处理。

    这是一个便利包装函数，内部调用项目级处理。

    使用场景：
    - 客服手动恢复服务
    - 客服上线
    - 客服结束当前会话

    Args:
        staff_id: 变为可用的客服ID（用于日志记录）
        project_id: 客服所属的项目ID
    """
    logger.info(
        f"Staff {staff_id} triggered queue processing for project {project_id}",
        extra={"staff_id": str(staff_id), "project_id": str(project_id)}
    )
    await trigger_queue_for_project(project_id)


# =============================================================================
# 内部队列处理核心逻辑
# =============================================================================

async def _process_project_queue_internal(project_id: UUID) -> None:
    """
    处理项目等待队列的内部方法。

    执行流程：
    1. 获取该项目中所有等待中的队列条目（按优先级和位置排序）
    2. 依次尝试将每个等待访客分配给可用客服
    3. 一旦某个访客无法分配（无可用客服），停止处理该批次
    4. 成功分配的访客从队列中移除（标记为已分配）

    设计考量：
    - 使用信号量控制并发处理数
    - 使用独立数据库会话避免事务冲突
    - 批量处理限制（QUEUE_PROCESS_BATCH_SIZE）
    - 一旦无可用客服就停止处理，避免无效循环

    Args:
        project_id: 要处理队列的项目ID
    """
    # 延迟导入以避免循环依赖
    from app.services.transfer_service import transfer_to_staff
    from app.models import AssignmentSource

    semaphore = _get_semaphore()

    try:
        # 使用信号量控制并发
        async with semaphore:
            db = SessionLocal()
            try:
                # =============================================================
                # 步骤1: 查询等待队列条目
                # =============================================================
                waiting_entries = (
                    db.query(VisitorWaitingQueue)
                    .filter(
                        VisitorWaitingQueue.project_id == project_id,
                        VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
                        # 只处理未过期的条目
                        (
                            (VisitorWaitingQueue.expired_at.is_(None)) |
                            (VisitorWaitingQueue.expired_at > func.now())
                        ),
                    )
                    .order_by(
                        VisitorWaitingQueue.priority.desc(),  # 高优先级优先
                        VisitorWaitingQueue.position.asc(),   # 同优先级下位置靠前优先
                    )
                    .limit(settings.QUEUE_PROCESS_BATCH_SIZE)  # 限制批次大小
                    .all()
                )

                if not waiting_entries:
                    logger.debug(f"No waiting entries for project {project_id}")
                    return

                logger.info(
                    f"Processing {len(waiting_entries)} waiting entries for project {project_id}",
                    extra={"project_id": str(project_id), "count": len(waiting_entries)}
                )

                # =============================================================
                # 步骤2: 逐个处理队列条目
                # =============================================================
                assigned_count = 0
                for entry in waiting_entries:
                    try:
                        # 记录本次尝试时间
                        entry.record_attempt()

                        # 调用转接服务尝试分配客服
                        result = await transfer_to_staff(
                            db=db,
                            visitor_id=entry.visitor_id,
                            project_id=project_id,
                            source=AssignmentSource.RULE,       # 来源：规则触发
                            visitor_message=entry.visitor_message,
                            session_id=entry.session_id,
                            notes=f"From queue trigger (entry_id={entry.id})",
                            skip_queue_status_check=True,       # 跳过状态检查（已在队列中）
                            auto_commit=False,                  # 手动控制提交
                            ai_disabled=entry.ai_disabled,
                            add_to_queue_if_no_staff=False,     # 已在队列中，不要再添加
                        )

                        # =====================================================
                        # 步骤3: 处理分配结果
                        # =====================================================
                        if result.success and result.assigned_staff_id:
                            # 分配成功 - 更新队列条目状态
                            entry.assign_to_staff(result.assigned_staff_id)
                            db.commit()
                            assigned_count += 1
                            logger.info(
                                f"Queue entry {entry.id} assigned to staff {result.assigned_staff_id}",
                                extra={
                                    "entry_id": str(entry.id),
                                    "visitor_id": str(entry.visitor_id),
                                    "staff_id": str(result.assigned_staff_id),
                                }
                            )
                        else:
                            # 分配失败 - 无可用客服
                            # 由于队列是按优先级排序的，如果当前访客无法分配，
                            # 后续访客也无法分配（因为同一批客服资源没有变化），
                            # 所以停止处理后续条目
                            db.commit()  # 提交尝试记录
                            logger.debug(
                                f"No staff available for entry {entry.id}, stopping batch",
                                extra={"entry_id": str(entry.id)}
                            )
                            break

                    except Exception as e:
                        logger.error(
                            f"Error processing queue entry {entry.id}: {e}",
                            extra={"entry_id": str(entry.id)}
                        )
                        try:
                            db.rollback()
                        except Exception:
                            pass  # 忽略回滚异常

                logger.info(
                    f"Queue processing complete for project {project_id}",
                    extra={
                        "project_id": str(project_id),
                        "assigned_count": assigned_count,
                        "total_processed": len(waiting_entries),
                    }
                )

            finally:
                db.close()

    except Exception as e:
        logger.exception(f"Error in queue processing for project {project_id}: {e}")
    finally:
        # =============================================================
        # 步骤4: 清理处理标记
        # =============================================================
        # 无论处理成功还是失败，都要从处理集合中移除项目ID
        async with _processing_lock:
            _processing_project_ids.discard(project_id)


# =============================================================================
# 单条目即时处理
# =============================================================================

async def trigger_queue_for_entry(entry_id: UUID) -> bool:
    """
    为特定的队列条目触发即时处理。

    当访客进入队列时调用此函数，尝试立即分配客服。

    与项目级处理的区别：
    - 只处理单个条目（不是批次）
    - 同步等待结果（返回成功/失败）
    - 适用于访客刚入队时的快速响应

    Args:
        entry_id: 要处理的队列条目ID

    Returns:
        bool: 成功分配返回 True，否则返回 False
    """
    # 延迟导入以避免循环依赖
    from app.services.transfer_service import transfer_to_staff
    from app.models import AssignmentSource

    semaphore = _get_semaphore()

    try:
        # 使用信号量控制并发
        async with semaphore:
            db = SessionLocal()
            try:
                # =============================================================
                # 步骤1: 获取队列条目
                # =============================================================
                entry = (
                    db.query(VisitorWaitingQueue)
                    .filter(
                        VisitorWaitingQueue.id == entry_id,
                        VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
                    )
                    .first()
                )

                if not entry:
                    logger.debug(f"Queue entry {entry_id} not found or not waiting")
                    return False

                # 记录本次尝试时间
                entry.record_attempt()

                # =============================================================
                # 步骤2: 尝试分配
                # =============================================================
                result = await transfer_to_staff(
                    db=db,
                    visitor_id=entry.visitor_id,
                    project_id=entry.project_id,
                    source=AssignmentSource.RULE,
                    visitor_message=entry.visitor_message,
                    session_id=entry.session_id,
                    notes=f"Immediate processing (entry_id={entry.id})",
                    skip_queue_status_check=True,
                    auto_commit=False,
                    ai_disabled=entry.ai_disabled,
                    add_to_queue_if_no_staff=False,  # 已在队列中
                )

                # =============================================================
                # 步骤3: 处理结果
                # =============================================================
                if result.success and result.assigned_staff_id:
                    # 分配成功 - 更新队列条目状态
                    entry.assign_to_staff(result.assigned_staff_id)
                    db.commit()
                    logger.info(
                        f"Queue entry {entry_id} immediately assigned to staff {result.assigned_staff_id}",
                        extra={
                            "entry_id": str(entry_id),
                            "staff_id": str(result.assigned_staff_id),
                        }
                    )
                    return True
                else:
                    # 分配失败 - 提交尝试记录，访客继续留在队列中
                    db.commit()
                    logger.debug(f"No staff available for immediate assignment of entry {entry_id}")
                    return False

            finally:
                db.close()

    except Exception as e:
        logger.error(f"Error in immediate queue processing for entry {entry_id}: {e}")
        return False