# =============================================================================
# 模块：等待队列管理任务 (Waiting queue management tasks)
# =============================================================================
# 该模块提供了以下功能：
# 1. 降级处理 (Fallback processing) - 低频定期处理可能被遗漏的队列条目
# 2. 过期条目清理 (Expired entries cleanup) - 定期清理过期的队列条目
# 3. 遗留触发器函数 (Legacy trigger function) - 为了向后兼容而保留的旧版触发函数
# =============================================================================

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Set
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings          # 应用配置（含队列相关参数）
from app.core.database import SessionLocal   # 数据库会话工厂
from app.core.logging import get_logger      # 日志记录器
from app.models import (
    Visitor,
    VisitorServiceStatus,
    VisitorWaitingQueue,
    WaitingStatus,
    AssignmentSource,
)
from app.services.transfer_service import transfer_to_staff   # 将访客转接给客服的核心服务

logger = get_logger("tasks.process_waiting_queue")   # 模块专用日志记录器

# -----------------------------------------------------------------------------
# 全局状态变量（用于任务生命周期管理和并发控制）
# -----------------------------------------------------------------------------
_fallback_task: Optional[asyncio.Task] = None   # 降级处理任务的句柄
_cleanup_task: Optional[asyncio.Task] = None    # 清理任务的句柄
_processing_lock = asyncio.Lock()               # 保护 _processing_ids 集合的锁
_processing_ids: Set[UUID] = set()              # 当前正在被处理的队列条目ID集合（防止重复处理）
_semaphore: Optional[asyncio.Semaphore] = None  # 控制并发处理数量的信号量


def _get_semaphore() -> asyncio.Semaphore:
    """
    获取或创建用于控制并发处理数量的信号量。
    信号量的最大值由配置项 QUEUE_PROCESS_MAX_WORKERS 决定。
    """
    global _semaphore
    if _semaphore is None:
        # 从配置中读取最大并发工作数，并创建信号量
        _semaphore = asyncio.Semaphore(settings.QUEUE_PROCESS_MAX_WORKERS)
    return _semaphore


# =============================================================================
# 第一部分：降级处理 (Fallback Processing)
# 说明：低频定期扫描，用于捕获因事件触发失败、系统重启或客服状态变化而未及时处理的队列条目。
# =============================================================================

async def _process_fallback_batch() -> None:
    """
    降级批量处理函数。

    处理逻辑：
    1. 从数据库中查询状态为 WAITING 且未过期（expired_at 为空或大于当前时间）的队列条目。
    2. 仅处理那些上次尝试时间早于（当前时间 - 降级间隔）的条目，避免重复频繁尝试。
    3. 按优先级（priority 降序）和位置（position 升序）排序，并限制批次大小。
    4. 使用锁机制过滤掉已经在处理中的条目，防止并发重复处理。
    5. 按 project_id 分组，对每个项目内的条目依次尝试转接给客服。
    6. 一旦某个项目转接失败（无可用客服），则停止处理该项目剩余条目（避免无效操作）。
    7. 记录每次尝试并更新数据库，成功转接则更新条目状态为已分配。
    """
    db = SessionLocal()  # 创建数据库会话
    try:
        # 计算降级处理的时间阈值：距离上次尝试必须超过 fallback_interval 秒
        fallback_delay = timedelta(seconds=settings.QUEUE_FALLBACK_INTERVAL_SECONDS)
        cutoff_time = datetime.utcnow() - fallback_delay

        # 查询需要降级处理的条目（条件见注释）
        entries = (
            db.query(VisitorWaitingQueue)
            .filter(
                VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
                # 未过期（expired_at 为NULL 或 未来时间）
                (VisitorWaitingQueue.expired_at.is_(None)) |
                (VisitorWaitingQueue.expired_at > func.now()),
                # 上次尝试时间早于 cutoff_time（即超过间隔未尝试）
                (VisitorWaitingQueue.last_attempt_at.is_(None)) |
                (VisitorWaitingQueue.last_attempt_at < cutoff_time),
            )
            .order_by(
                VisitorWaitingQueue.priority.desc(),  # 高优先级优先
                VisitorWaitingQueue.position.asc(),   # 同一优先级下位置靠前优先
            )
            .limit(settings.QUEUE_PROCESS_BATCH_SIZE)  # 限制批次大小
            .all()
        )

        if not entries:
            logger.debug("Fallback processor: no entries to process")
            return

        # 使用锁过滤掉正在处理中的条目，并将本次要处理的条目加入处理集合
        async with _processing_lock:
            entries_to_process = [e for e in entries if e.id not in _processing_ids]
            for e in entries_to_process:
                _processing_ids.add(e.id)

        if not entries_to_process:
            logger.debug("Fallback processor: all entries already being processed")
            return

        logger.info(
            f"Fallback processor: processing {len(entries_to_process)} entries",
            extra={"count": len(entries_to_process)},
        )

        # 按项目（project_id）分组，以便按项目逐个处理
        project_entries: dict[UUID, list[VisitorWaitingQueue]] = {}
        for entry in entries_to_process:
            if entry.project_id not in project_entries:
                project_entries[entry.project_id] = []
            project_entries[entry.project_id].append(entry)

        # 获取信号量，控制并行处理的项目数量
        semaphore = _get_semaphore()

        # 定义处理单个项目内所有条目的异步函数
        async def process_project_entries(
            project_id: UUID,
            entries: list[VisitorWaitingQueue]
        ) -> tuple[int, int]:
            """返回 (assigned 成功分配数, processed 处理尝试数)"""
            async with semaphore:   # 受信号量限制并发数
                entry_db = SessionLocal()   # 每个项目使用独立的数据库会话
                assigned = 0
                processed = 0
                try:
                    for entry in entries:
                        try:
                            # 重新查询条目，确保获取最新的状态（避免处理已变更的条目）
                            fresh_entry = (
                                entry_db.query(VisitorWaitingQueue)
                                .filter(
                                    VisitorWaitingQueue.id == entry.id,
                                    VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
                                )
                                .first()
                            )
                            if not fresh_entry:
                                continue   # 条目已被处理或状态变更，跳过

                            # 记录本次尝试时间（last_attempt_at 更新）
                            fresh_entry.record_attempt()
                            processed += 1

                            # 调用核心转接服务，尝试将访客分配给客服
                            result = await transfer_to_staff(
                                db=entry_db,
                                visitor_id=fresh_entry.visitor_id,
                                project_id=project_id,
                                source=AssignmentSource.RULE,      # 来源：规则触发
                                visitor_message=fresh_entry.visitor_message,
                                session_id=fresh_entry.session_id,
                                notes=f"Fallback processing (entry_id={fresh_entry.id})",
                                skip_queue_status_check=True,      # 跳过队列状态检查（因为已在队列中）
                                auto_commit=False,                 # 手动控制提交
                                add_to_queue_if_no_staff=False,    # 已在队列中，不要再添加
                            )

                            # 如果转接成功且有分配的客服，更新队列条目状态
                            if result.success and result.assigned_staff_id:
                                fresh_entry.assign_to_staff(result.assigned_staff_id)
                                entry_db.commit()
                                assigned += 1
                                logger.info(
                                    f"Fallback: entry {fresh_entry.id} assigned to {result.assigned_staff_id}",
                                    extra={
                                        "entry_id": str(fresh_entry.id),
                                        "staff_id": str(result.assigned_staff_id),
                                    }
                                )
                            else:
                                entry_db.commit()  # 即使未分配，也要提交尝试记录（last_attempt_at 更新）
                                # 如果当前项目没有可用客服，则停止处理该项目剩余条目
                                break

                        except Exception as e:
                            logger.error(f"Fallback: error processing entry {entry.id}: {e}")
                            try:
                                entry_db.rollback()
                            except Exception:
                                pass   # 忽略回滚异常

                    return assigned, processed
                finally:
                    entry_db.close()   # 确保会话关闭

        # 并行处理所有项目的条目（每个项目受信号量限制）
        tasks = [
            process_project_entries(pid, pentries)
            for pid, pentries in project_entries.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 汇总处理结果
        total_assigned = 0
        total_processed = 0
        for result in results:
            if isinstance(result, tuple):
                total_assigned += result[0]
                total_processed += result[1]

        # 从处理集合中移除本次处理的条目ID（释放锁资源）
        async with _processing_lock:
            for e in entries_to_process:
                _processing_ids.discard(e.id)

        logger.info(
            f"Fallback processor: batch complete",
            extra={
                "total": len(entries_to_process),
                "processed": total_processed,
                "assigned": total_assigned,
            },
        )

    except Exception as e:
        logger.exception(f"Fallback processor: batch exception: {e}")
    finally:
        db.close()   # 确保数据库会话关闭


async def _fallback_loop() -> None:
    """
    降级处理循环。
    按照配置的间隔（QUEUE_FALLBACK_INTERVAL_SECONDS）反复执行 _process_fallback_batch。
    """
    interval_sec = max(1, settings.QUEUE_FALLBACK_INTERVAL_SECONDS)  # 至少1秒
    while True:
        try:
            await _process_fallback_batch()
        except Exception as e:
            logger.exception(f"Fallback processor loop exception: {e}")
        await asyncio.sleep(interval_sec)


# =============================================================================
# 第二部分：过期条目清理 (Expired Entries Cleanup)
# 说明：定期扫描过期的等待队列条目，将其标记为 EXPIRED，并重置访客的服务状态。
# =============================================================================

async def _cleanup_expired_entries() -> None:
    """
    清理过期队列条目。

    执行操作：
    1. 查询状态为 WAITING 且 expired_at 小于当前时间的条目（限制批次100）。
    2. 对每个条目调用 expire() 方法，将其状态更新为 EXPIRED。
    3. 如果对应访客的服务状态是 QUEUED（排队中），则重置为 CLOSED。
    4. 提交数据库事务。
    5. （TODO）发送通知给访客告知排队超时。
    """
    db = SessionLocal()
    try:
        # 查询过期条目（状态为WAITING且过期时间已到）
        expired_entries = (
            db.query(VisitorWaitingQueue)
            .filter(
                VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
                VisitorWaitingQueue.expired_at.isnot(None),
                VisitorWaitingQueue.expired_at < func.now(),
            )
            .limit(100)   # 分批处理，避免一次处理过多
            .all()
        )

        if not expired_entries:
            logger.debug("Cleanup: no expired entries found")
            return

        logger.info(
            f"Cleanup: processing {len(expired_entries)} expired entries",
            extra={"count": len(expired_entries)},
        )

        for entry in expired_entries:
            try:
                # 将条目状态更新为 EXPIRED
                entry.expire()

                # 获取对应的访客记录
                visitor = db.query(Visitor).filter(
                    Visitor.id == entry.visitor_id
                ).first()

                # 如果访客服务状态为 QUEUED，则将其重置为 CLOSED
                if visitor and visitor.service_status == VisitorServiceStatus.QUEUED.value:
                    visitor.service_status = VisitorServiceStatus.CLOSED.value
                    visitor.updated_at = datetime.utcnow()

                db.commit()

                logger.info(
                    f"Cleanup: expired entry {entry.id}",
                    extra={
                        "entry_id": str(entry.id),
                        "visitor_id": str(entry.visitor_id),
                        "wait_seconds": entry.wait_duration_seconds,
                    }
                )

                # TODO: 发送通知给访客告知排队超时（预留扩展点）
                # await notify_visitor_queue_expired(entry.visitor_id)

            except Exception as e:
                logger.error(f"Cleanup: error expiring entry {entry.id}: {e}")
                try:
                    db.rollback()
                except Exception:
                    pass   # 忽略回滚异常

    except Exception as e:
        logger.exception(f"Cleanup: exception: {e}")
    finally:
        db.close()


async def _cleanup_loop() -> None:
    """
    清理任务循环。
    按照配置的间隔（QUEUE_CLEANUP_INTERVAL_SECONDS）反复执行 _cleanup_expired_entries。
    """
    interval_sec = max(1, settings.QUEUE_CLEANUP_INTERVAL_SECONDS)  # 至少1秒
    while True:
        try:
            await _cleanup_expired_entries()
        except Exception as e:
            logger.exception(f"Cleanup loop exception: {e}")
        await asyncio.sleep(interval_sec)


# =============================================================================
# 第三部分：任务生命周期管理 (Task Lifecycle Management)
# 说明：提供启动和停止后台任务的功能，在应用启动/关闭时调用。
# =============================================================================

def start_queue_tasks() -> None:
    """
    启动队列处理后台任务。
    包括：
    - 降级处理任务（如果配置启用）
    - 过期条目清理任务
    """
    global _fallback_task, _cleanup_task

    # 启动降级处理器（如果配置启用）
    if settings.QUEUE_FALLBACK_ENABLED:
        if _fallback_task is None or _fallback_task.done():
            try:
                _fallback_task = asyncio.create_task(_fallback_loop())
                logger.info(
                    "Queue fallback processor started",
                    extra={"interval_seconds": settings.QUEUE_FALLBACK_INTERVAL_SECONDS},
                )
            except Exception as e:
                logger.warning(f"Failed to start fallback processor: {e}")
    else:
        logger.info("Queue fallback processor disabled by config")

    # 启动清理任务（始终启动）
    if _cleanup_task is None or _cleanup_task.done():
        try:
            _cleanup_task = asyncio.create_task(_cleanup_loop())
            logger.info(
                "Queue cleanup task started",
                extra={"interval_seconds": settings.QUEUE_CLEANUP_INTERVAL_SECONDS},
            )
        except Exception as e:
            logger.warning(f"Failed to start cleanup task: {e}")


async def stop_queue_tasks() -> None:
    """
    停止队列处理后台任务。
    取消所有任务并等待其完成（或取消），然后清空全局句柄。
    """
    global _fallback_task, _cleanup_task

    tasks_to_stop = []

    if _fallback_task:
        _fallback_task.cancel()
        tasks_to_stop.append(_fallback_task)

    if _cleanup_task:
        _cleanup_task.cancel()
        tasks_to_stop.append(_cleanup_task)

    # 等待所有任务被取消或完成
    for task in tasks_to_stop:
        try:
            await task
        except asyncio.CancelledError:
            pass   # 任务被正常取消
        except Exception:
            pass   # 忽略其他异常

    _fallback_task = None
    _cleanup_task = None
    logger.info("Queue tasks stopped")


# =============================================================================
# 第四部分：遗留函数 (Legacy Functions)
# 说明：为保持向后兼容而保留的旧接口，内部委托给新的服务实现。
# =============================================================================

async def trigger_process_entry(entry_id: UUID) -> None:
    """
    触发处理指定的队列条目（向后兼容包装函数）。

    该函数是旧版API的占位，实际逻辑委托给 queue_trigger_service 模块中的
    trigger_queue_for_entry 函数。

    Args:
        entry_id: VisitorWaitingQueue 条目的 UUID
    """
    from app.services.queue_trigger_service import trigger_queue_for_entry
    await trigger_queue_for_entry(entry_id)


# 为保持向后兼容，提供旧名称的别名
start_queue_processor = start_queue_tasks
stop_queue_processor = stop_queue_tasks