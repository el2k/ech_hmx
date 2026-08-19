"""Platform synchronization scheduling and event triggers.

这个模块负责“平台数据同步”相关的后台调度逻辑，主要包含三部分：

1. trigger_platform_sync:
   把某个平台的“新增/更新同步”任务放进内存队列

2. trigger_platform_delete:
   把某个平台的“删除同步”任务放进内存队列

3. start_sync_monitor:
   启动后台异步任务，持续消费队列并处理失败重试

当前实现是基于 asyncio 的“轻量级队列 + 后台任务”方案，
适合单进程/简单部署。

注意：
- 这里的队列是内存队列，服务重启后队列会丢失
- 多进程部署时，各进程之间不会共享这个队列
- 更稳妥的方案是 Redis / Celery / RabbitMQ 这类共享任务队列
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.platform import Platform
from app.services.platform_sync_client import platform_sync_client

# 当前模块日志对象
logger = logging.getLogger(__name__)



@dataclass
class PlatformSyncJob:
    """
    平台同步任务的数据结构。

    只保存最基本的信息：
    - platform_id: 要同步的平台 ID
    - action: 动作类型
        - "upsert"：新增或更新同步
        - "delete"：删除同步
    """
    platform_id: str
    action: str  # 'upsert' | 'delete'


# asyncio 内存队列：
# 所有同步任务先进入这里，再由后台 consumer 逐个处理
_queue: "asyncio.Queue[PlatformSyncJob]" = asyncio.Queue()

# 后台消费者任务句柄
_consumer_task: Optional[asyncio.Task] = None

# 后台重试任务句柄
_retry_task: Optional[asyncio.Task] = None


def _now() -> datetime:
    """
    返回当前 UTC 时间。
    统一用 UTC，避免跨时区时间计算出错。
    """
    return datetime.now(timezone.utc)


def _to_aware(dt: datetime) -> datetime:
    """
    把 datetime 规范化为“带时区”的 UTC 时间。

    作用：
    - 如果原始时间是 naive datetime（没有 tzinfo）
      就直接补上 UTC 时区
    - 如果原始时间已经带时区
      就转换成 UTC

    这样后续做时间差计算更安全。
    """
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _mark_status(
    db: Session,
    platform: Platform,
    status: str,
    *,
    error: Optional[str] = None,
    inc_retry: bool = False,
) -> None:
    """
    更新平台同步状态，并提交数据库。

    参数说明：
    - status: 新状态，比如 pending / synced / failed
    - error: 失败原因，最多记录 1000 字符
    - inc_retry: 是否增加重试次数

    状态逻辑：
    - synced:
        同步成功，更新 last_synced_at，清空错误和重试计数
    - 其他状态:
        可以记录错误信息
        如果 inc_retry=True，就把 sync_retry_count + 1
    """
    platform.sync_status = status

    if status == "synced":
        # 同步成功：记录最近同步时间
        platform.last_synced_at = _now()
        # 清空错误信息
        platform.sync_error = None
        # 清空重试次数
        platform.sync_retry_count = 0
    else:
        # 同步失败或 pending 等状态，按需写入错误
        if error:
            platform.sync_error = (error or "")[:1000]
        # 是否累加重试次数
        if inc_retry:
            platform.sync_retry_count = (platform.sync_retry_count or 0) + 1

    # SQLAlchemy 追踪对象变更
    db.add(platform)
    # 立即提交，让状态落库
    db.commit()


def trigger_platform_sync(platform_id: str) -> None:
    """
    触发某个平台的“新增/更新同步”任务。

    这里不直接执行同步，而是：
    1. 构造一个 PlatformSyncJob
    2. 放入内存队列
    3. 由后台 consumer 异步处理

    这样可以避免在业务请求线程里直接等待远程同步接口返回。
    """
    try:
        _queue.put_nowait(PlatformSyncJob(platform_id=platform_id, action="upsert"))
    except Exception:
        # 队列放入失败时记录日志
        logger.exception("Failed to enqueue platform sync", extra={"platform_id": platform_id})


def trigger_platform_delete(platform_id: str) -> None:
    """
    触发某个平台的“删除同步”任务。

    和 trigger_platform_sync 类似，只是 action 变成 delete。
    """
    try:
        _queue.put_nowait(PlatformSyncJob(platform_id=platform_id, action="delete"))
    except Exception:
        logger.exception("Failed to enqueue platform delete", extra={"platform_id": platform_id})


async def _process_job(job: PlatformSyncJob) -> None:
    """
    处理单个同步任务。

    执行流程：
    1. 打开数据库会话
    2. 根据 platform_id 查本地平台记录
    3. 根据 action 决定同步逻辑
    4. 调远程 platform_sync_client 同步到平台服务
    5. 根据结果更新本地 sync_status
    """
    db: Session = SessionLocal()
    try:
        # 从数据库查出对应平台
        platform: Optional[Platform] = db.get(Platform, job.platform_id)

        # 删除任务的特殊处理：
        # 如果本地记录已经被硬删除，platform 可能不存在
        if job.action == "delete":
            if platform is None:
                # 本地没有记录时，尝试直接请求远端删除
                try:
                    await platform_sync_client.delete_platform(job.platform_id)
                except Exception as exc:
                    logger.warning(
                        "Remote delete failed",
                        extra={"platform_id": job.platform_id, "error": str(exc)},
                    )
                return

        # 如果不是删除任务，或者平台不存在，就直接返回
        if not platform:
            return

        # 先把状态标记为 pending
        # 目的：
        # - 让数据库里能看到“正在同步中”
        # - 避免重复触发时状态混乱
        # - 这里只改同步字段，不改业务字段，避免触发额外副作用
        platform.sync_status = "pending"
        platform.sync_error = None
        db.add(platform)
        db.commit()

        # 组装要同步到远端平台服务的数据
        data = {
            "id": str(platform.id),
            "project_id": str(platform.project_id),
            "name": platform.name,
            "type": platform.type,
            "config": platform.config,
            "is_active": platform.is_active and platform.deleted_at is None,
            "api_key": platform.api_key,
            "created_at": platform.created_at,
            "updated_at": platform.updated_at,
            "deleted_at": platform.deleted_at,
        }

        # 调用远端平台服务执行 upsert
        # 返回值 resp 一般包含 HTTP 状态码和响应内容
        resp = await platform_sync_client.upsert_platform(data)

        # 判断是否成功：2xx 认为成功
        ok = 200 <= resp.status_code < 300

        if ok:
            # 同步成功：更新为 synced
            _mark_status(db, platform, "synced")
        else:
            # 同步失败：写入错误信息并增加重试计数
            _mark_status(
                db,
                platform,
                "failed",
                error=f"HTTP {resp.status_code}: {resp.text}",
                inc_retry=True,
            )

    except Exception as exc:
        # 任务整体异常兜底
        logger.exception("Sync job failed", extra={"platform_id": job.platform_id})

        # 尽量把状态写成 failed
        # 注意：这里是 best-effort，不保证一定成功
        try:
            if "db" in locals():
                platform = locals().get("platform")
                if platform is not None:
                    _mark_status(db, platform, "failed", error=str(exc), inc_retry=True)
        except Exception:
            pass
    finally:
        # 无论成功失败，最终关闭数据库连接
        db.close()


async def _consumer_loop() -> None:
    """
    后台消费者循环。

    作用：
    - 一直等待队列里的任务
    - 取到一个就处理一个
    - 处理完后标记 task_done

    这是一个永不退出的 while True 循环，
    需要作为后台 task 常驻运行。
    """
    while True:
        # 阻塞等待队列中出现任务
        job = await _queue.get()

        # 处理任务
        await _process_job(job)

        # 告诉队列：当前任务完成
        _queue.task_done()


async def _retry_loop() -> None:
    """
    周期性扫描需要重试的平台。

    这个循环的目的：
    - 防止某些同步任务因为事件丢失、进程重启、异常中断而没有被重新投递
    - 定期扫描数据库，把未同步成功的记录重新放回队列

    重试策略：
    - 只扫描 sync_status != 'synced' 的平台
    - 使用指数退避：
        delay = base * (2 ** min(retry_count, 5))
      retry 次数越多，等待时间越长，避免频繁重试
    """
    while True:
        # 每隔固定时间扫描一次数据库
        await asyncio.sleep(settings.PLATFORM_SYNC_RETRY_INTERVAL_SECONDS)

        db: Session = SessionLocal()
        try:
            # 只取一批，避免扫描太多数据导致耗时过长
            rows = (
                db.query(Platform)
                .filter(Platform.sync_status != "synced")
                .limit(settings.PLATFORM_SYNC_BATCH_LIMIT)
                .all()
            )

            for p in rows:
                # 当前已重试次数
                retry_count = p.sync_retry_count or 0

                # 基础重试间隔
                base = settings.PLATFORM_SYNC_RETRY_INTERVAL_SECONDS

                # 指数退避：重试次数越多，间隔越长
                # 例如：
                # retry_count=0 -> delay=base
                # retry_count=1 -> delay=2*base
                # retry_count=2 -> delay=4*base
                # ...
                # 最大指数只放大到 2^5，避免无限增大
                delay = base * (2 ** min(retry_count, 5))

                # 取一个“上次尝试时间”
                # 优先级：
                # last_synced_at -> updated_at -> created_at
                last = p.last_synced_at or p.updated_at or p.created_at

                if last is None:
                    # 实在没有时间就用当前时间兜底
                    last = _now()
                else:
                    # 统一转成 UTC aware 时间
                    last = _to_aware(last)

                # 如果距离上次时间已经超过 delay，就重新入队
                if (_now() - last).total_seconds() >= delay:
                    trigger_platform_sync(str(p.id))

        except Exception:
            logger.exception("Retry loop failed")
        finally:
            db.close()


def start_sync_monitor() -> None:
    """
    启动平台同步监控后台任务。

    这里启动两个异步 task：

    1. _consumer_loop
       - 负责实时消费同步队列
       - 处理 trigger_platform_sync / trigger_platform_delete 放入的任务

    2. _retry_loop
       - 负责周期性扫描失败或未同步的平台
       - 把需要重试的任务重新放回队列

    为什么要判断 task 是否已经存在或 done？
    - 防止重复启动多个消费者
    - 防止重复启动多个重试循环
    - 避免同一进程内出现重复消费和重复重试
    """
    global _consumer_task, _retry_task

    # 如果消费者任务不存在，或者已经结束，就重新创建
    if _consumer_task is None or _consumer_task.done():
        _consumer_task = asyncio.create_task(_consumer_loop())
        logger.info("Platform sync consumer started")

    # 如果重试任务不存在，或者已经结束，就重新创建
    if _retry_task is None or _retry_task.done():
        _retry_task = asyncio.create_task(_retry_loop())
        logger.info("Platform sync retry started")