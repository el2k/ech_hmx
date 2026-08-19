"""嵌入模型配置同步的周期重试任务。

该调度器查询状态为 failed / not_synced，或是长时间处于 pending 僵死状态的 ProjectAIConfig 记录，
调用已有 fire_and_forget_embedding_sync() 机制重新向 RAG 服务发起同步。

这是一个轻量 asyncio 循环任务，受 app.config.Settings 中的配置开关与间隔参数控制。
默认关闭，配置 EMBEDDING_SYNC_RETRY_ENABLED=true 即可启用。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List

from sqlalchemy import and_, or_, select

from app.config import settings
from app.core.logging import get_logger
from app.database import AsyncSessionLocal
from app.models.project_ai_config import ProjectAIConfig
from app.services.rag_embedding_sync_service import (
    build_embedding_configs,
    fire_and_forget_embedding_sync,
)

logger = get_logger("tasks.embedding_sync_retry")

# 进程内锁，防止任务并发重复执行
_run_lock = asyncio.Lock()

'''
后台周期巡检任务，兜底补偿同步。
业务触发同步（新建 / 修改项目 AI 配置）走 fire_and_forget_embedding_sync；
而本定时任务负责捞取：同步失败、从未同步、pending 僵死超时的记录，重新发起同步。'''
async def _collect_retry_candidates() -> List[ProjectAIConfig]:
    """根据同步状态、时间阈值、最大尝试次数筛选需要重试的配置记录。"""
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.embedding_sync_retry_stale_pending_minutes
    )
    max_attempts = settings.embedding_sync_retry_max_attempts

    async with AsyncSessionLocal() as session:
        stmt = select(ProjectAIConfig).where(
            and_(
                or_(
                    ProjectAIConfig.sync_status == "failed",
                    ProjectAIConfig.sync_status == "not_synced",
                    and_(
                        ProjectAIConfig.sync_status == "pending",
                        ProjectAIConfig.updated_at < cutoff,
                    ),
                ),
                or_(
                    ProjectAIConfig.sync_attempt_count.is_(None),
                    ProjectAIConfig.sync_attempt_count < max_attempts,
                ),
            )
        )
        res = await session.execute(stmt)
        rows: List[ProjectAIConfig] = list(res.scalars().all())
        return rows


async def run_retry_once() -> int:
    """执行一轮重试扫描，返回本次实际发起同步的配置数量。"""
    async with _run_lock:
        rows = await _collect_retry_candidates()
        if not rows:
            logger.info("embedding‑sync‑retry: 未找到待重试记录")
            return 0
        print("run_retry_once....", rows)
        async with AsyncSessionLocal() as session:
            configs = await build_embedding_configs(session, rows)
        if not configs:
            logger.info(
                "embedding‑sync‑retry: 候选记录无合法嵌入模型配置",
                count=len(rows),
            )
            return 0

        fire_and_forget_embedding_sync(configs)
        logger.info(
            "embedding‑sync‑retry: 已下发同步任务",
            candidates=len(rows),
            dispatched=len(configs),
        )
        return len(configs)


async def start_embedding_sync_retry_loop(stop_event: asyncio.Event) -> None:
    """启动周期执行的异步重试循环。

    先等待一个配置间隔再执行第一轮扫描，之后每间隔周期执行一次。
    收到 stop_event 信号后退出循环。
    """
    print("start_embedding_sync_retry_loop....")
    if not settings.embedding_sync_retry_enabled:
        logger.info("embedding‑sync‑retry: 配置关闭，不启动重试循环")
        return

    interval = max(30, int(settings.embedding_sync_retry_interval_seconds))
    logger.info(
        "embedding‑sync‑retry: 启动周期重试循环",
        interval_seconds=interval,
        max_attempts=settings.embedding_sync_retry_max_attempts,
        stale_pending_minutes=settings.embedding_sync_retry_stale_pending_minutes,
    )

    # 首次执行前等待一个间隔，避免服务启动瞬间大量抢占请求，也便于单元测试
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=interval)
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            await run_retry_once()
        except Exception as e:  # pragma: no cover 防御性捕获
            logger.error("embedding‑sync‑retry: 本轮重试扫描异常", error=str(e))
        # 睡眠等待下一轮，可被 stop_event 提前终止
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue