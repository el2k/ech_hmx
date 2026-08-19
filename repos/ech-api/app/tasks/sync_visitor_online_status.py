# =============================================================================
# 模块：访客在线状态同步定时任务 (Periodic task to sync visitor online status)
# =============================================================================
# 该模块提供了定期同步访客在线状态的功能，主要包括：
# 1. 从数据库获取所有标记为在线的访客
# 2. 向 WuKongIM 查询这些访客的真实在线状态
# 3. 修正数据库中与实际状态不一致的记录
# 4. 将实际已离线的访客标记为离线
# 
# 设计目的：
# - 处理访客异常断开连接（如浏览器关闭、网络中断）导致的状态不一致
# - 确保数据库中的在线状态与 IM 系统保持同步
# - 为其他模块（如客服分配、状态展示）提供准确的数据基础
# =============================================================================

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models import Visitor
from app.services.wukongim_client import wukongim_client

logger = get_logger("tasks.sync_visitor_online_status")

# =============================================================================
# 全局状态变量（用于任务生命周期管理和并发控制）
# =============================================================================
_task: Optional[asyncio.Task] = None          # 后台任务的句柄
_processing_lock = asyncio.Lock()             # 防止并发执行同步任务的锁


# =============================================================================
# 核心处理函数
# =============================================================================

async def _process_online_status_sync() -> int:
    """
    同步访客在线状态与 WuKongIM。

    执行流程：
    1. 从数据库查询所有标记为在线的访客
    2. 分批处理这些访客（避免一次性处理过多）
    3. 通过 WuKongIM API 批量查询这些访客的真实在线状态
    4. 将数据库中在线但 IM 中已离线的访客标记为离线
    5. 记录修正时间（last_offline_time）

    设计考量：
    - 只检查数据库中标记为在线的访客（减少不必要的查询）
    - 使用批量处理控制每批数量（VISITOR_ONLINE_SYNC_BATCH_SIZE）
    - 批量查询 IM 状态，减少 API 调用次数
    - 单批失败不影响其他批次

    Returns:
        int: 被修正为离线的访客数量
    """
    db: Session = SessionLocal()
    marked_offline_count = 0

    try:
        # =====================================================================
        # 步骤1: 查询数据库中所有标记为在线的访客
        # =====================================================================
        # 只处理 is_online = True 的访客，减少查询范围
        online_visitors = (
            db.query(Visitor)
            .filter(Visitor.is_online == True)
            .all()
        )

        if not online_visitors:
            return 0

        logger.debug(f"Found {len(online_visitors)} visitors marked as online in DB")

        # =====================================================================
        # 步骤2: 分批处理
        # =====================================================================
        # 使用批量处理避免一次性处理过多导致性能问题
        batch_size = settings.VISITOR_ONLINE_SYNC_BATCH_SIZE
        for i in range(0, len(online_visitors), batch_size):
            batch = online_visitors[i : i + batch_size]

            # 构建访客 UID 到访客对象的映射
            # WuKongIM 中访客的 UID 格式为 "{visitor_id}-vtr"
            uid_to_visitor = {f"{v.id}-vtr": v for v in batch}
            uids = list(uid_to_visitor.keys())

            try:
                # =============================================================
                # 步骤3: 从 WuKongIM 查询真实在线状态
                # =============================================================
                # check_user_online_status 返回实际在线的 UID 列表
                actually_online_uids = await wukongim_client.check_user_online_status(uids)
                actually_online_set = set(actually_online_uids)

                # =============================================================
                # 步骤4: 识别并修正状态不一致的访客
                # =============================================================
                any_changes = False
                for uid, visitor in uid_to_visitor.items():
                    if uid not in actually_online_set:
                        # 访客在数据库中标记为在线，但在 WuKongIM 中已离线
                        # 这种情况可能发生在：
                        # - 访客直接关闭浏览器（未触发离线事件）
                        # - 网络中断导致连接断开
                        # - WuKongIM 连接超时
                        visitor.is_online = False
                        visitor.last_offline_time = datetime.utcnow()
                        marked_offline_count += 1
                        any_changes = True

                        logger.info(
                            f"Visitor {visitor.id} corrected to offline (sync)",
                            extra={"visitor_id": str(visitor.id)}
                        )

                # 批量提交变更
                if any_changes:
                    db.commit()

            except Exception as e:
                # 单批失败不影响其他批次
                logger.error(f"Error syncing batch of visitor online status: {e}")
                # 继续处理下一批

        return marked_offline_count

    except Exception as e:
        logger.error(f"Error in visitor online status sync process: {e}")
        return marked_offline_count
    finally:
        db.close()


# =============================================================================
# 定时任务循环
# =============================================================================

async def _run_periodic_task():
    """
    运行周期性的在线状态同步任务。

    这是一个无限循环，按照配置的间隔不断执行状态同步。
    使用锁防止在任务执行期间再次触发。
    """
    logger.info(
        f"Starting visitor online status sync task "
        f"(interval={settings.VISITOR_ONLINE_SYNC_INTERVAL_SECONDS}s)"
    )

    while True:
        try:
            # 使用锁防止并发执行
            async with _processing_lock:
                corrected_count = await _process_online_status_sync()
                if corrected_count > 0:
                    logger.info(f"Corrected {corrected_count} visitors to offline")
        except Exception as e:
            logger.error(f"Error in periodic online status sync: {e}")

        # 等待下一个检查周期
        await asyncio.sleep(settings.VISITOR_ONLINE_SYNC_INTERVAL_SECONDS)


# =============================================================================
# 任务生命周期管理
# =============================================================================

async def start_visitor_online_sync_task():
    """
    启动后台访客在线状态同步任务。

    在应用启动时调用此函数来启动定时任务。
    如果任务已禁用或已在运行，则相应处理。
    """
    global _task

    # 检查是否启用了在线状态同步
    if not settings.VISITOR_ONLINE_SYNC_ENABLED:
        logger.info("Visitor online status sync is disabled")
        return

    # 检查任务是否已在运行
    if _task is not None and not _task.done():
        logger.warning("Visitor online status sync task is already running")
        return

    # 创建并启动异步任务
    _task = asyncio.create_task(_run_periodic_task())
    logger.info("Visitor online status sync task started")


async def stop_visitor_online_sync_task():
    """
    停止后台访客在线状态同步任务。

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
    logger.info("Visitor online status sync task stopped")


# =============================================================================
# 手动触发接口
# =============================================================================

async def trigger_online_status_sync() -> int:
    """
    手动触发的访客在线状态同步。

    可从 API 端点调用，用于需要立即同步状态的场景。
    例如：管理员手动触发、测试场景、或系统启动后的首次同步。

    使用锁确保与定时任务不并发执行。

    Returns:
        int: 被修正为离线的访客数量
    """
    async with _processing_lock:
        return await _process_online_status_sync()