"""DingTalk Bot message consumer.

This module implements a producer-consumer pattern for DingTalk Bot messages:
- Producer: FastAPI callback endpoint stores messages into DingTalkInbox
- Consumer: This listener polls pending rows and processes them via dispatcher
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models import Platform, DingTalkInbox
from app.domain.entities import NormalizedMessage
from app.domain.ports import MessageNormalizer, TgoApiClient, SSEManager
from app.domain.services.dispatcher import process_message
from app.infra.visitor_client import VisitorService


class DingTalkPlatformConfig(BaseModel):
    """Per-platform DingTalk Bot configuration stored in Platform.config when type='dingtalk_bot'."""

    app_key: str = ""         # 应用Key
    app_secret: str = ""      # 应用Secret
    robot_code: str = ""      # 机器人编码
    aes_key: str | None = None  # 消息加密密钥（可选）
    token: str | None = None    # 签名 Token（可选）

    # Consumer processing configuration
    processing_batch_size: int = 10
    max_retry_attempts: int = 3
    consumer_poll_interval_seconds: int = 5


@dataclass
class _PlatformEntry:
    id: uuid.UUID
    project_id: uuid.UUID
    api_key: str | None
    cfg: DingTalkPlatformConfig

'''
生产者‑消费者（producer‑consumer）架构，处理钉钉机器人消息
Producer（生产者）：FastAPI 钉钉回调接口，收到钉钉推送的用户消息，写入数据库表 dingtalk_inbox（DingTalkInbox 模型），
快速返回 HTTP 给钉钉，不做 AI 处理。
Consumer（消费者）：DingTalkChannelListener，独立后台异步循环任务，轮询 dingtalk_inbox 待处理记录，
调用系统消息分发器 process_message 跑 Agent 业务，完成 AI 应答。
为什么要这么做？
钉钉 webhook 回调有超时限制；如果回调接口里面直接跑大模型推理，耗时很长，钉钉会超时重试，造成重复提问。
所以：回调只落库，真正 AI 处理交给后台轮询消费者。
'''
'''
完整消息流转链路（钉钉机器人）
用户在钉钉群 @机器人发消息 → 钉钉 HTTP 回调请求访问 FastAPI 接口
FastAPI 回调接口（Producer）：校验签名，把原始报文、session_webhook存入DingTalkInbox表，status=pending，立刻 HTTP 返回给钉钉，不跑大模型。
DingTalkChannelListener后台循环任务，轮询表，select ... for update skip_locked抢占行，状态改为processing。
组装消息，注册 / 获取访客，经过MessageNormalizer标准化为NormalizedMessage。
调用通用分发器 process_message()
内部读取extra.dingtalk.session_webhook
创建 DingTalkBotAdapter(session_webhook=xxx)
执行 Agent 推理；supports_stream=False丢弃分片，全部生成完毕执行send_final()调用钉钉 session_webhook 完成回复。
处理成功：inbox 记录 status 改为completed，存入ai_reply；失败 status=failed，retry_count +=1，指数退避等待下一轮重试。
'''
# 群机器人：加到群里，@它提问，消息走到你的后端，后端算出答案，再调用平台接口把回复打回群里。
# 不是机器人自己在运算，全部逻辑跑在你的 TGO 后端。
class DingTalkChannelListener:
    """DingTalk Bot consumer that processes pending dingtalk_inbox rows asynchronously.

    Producer: FastAPI callback endpoint stores messages into dingtalk_inbox.
    Consumer: This listener queries pending rows and processes them via dispatcher.
    """
    """
    钉钉机器人消费者后台任务，异步轮询 dingtalk_inbox 表处理待处理消息
    Producer：FastAPI回调接口写入dingtalk_inbox
    Consumer：本类循环查询pending记录，调用dispatcher处理消息
    """
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        normalizer: MessageNormalizer,
        tgo_api_client: TgoApiClient,
        sse_manager: SSEManager,
    ) -> None:
        self._session_factory = session_factory
        self._normalizer = normalizer
        self._tgo_api_client = tgo_api_client
        self._sse_manager = sse_manager
        self._stop_event = asyncio.Event()
        self._consumer_task: asyncio.Task | None = None
        self._visitor_service = VisitorService(
            base_url=settings.api_base_url,
            cache_ttl_seconds=300,
            redis_url=settings.redis_url,
        )
    """启动消费者后台协程任务"""
    async def start(self) -> None:
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consumer_loop())
    """优雅停止消费者任务"""
    async def stop(self) -> None:
        self._stop_event.set()
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
    """加载数据库中所有启用状态的 dingtalk_bot 类型平台"""            
    async def _load_active_dingtalk_platforms(self) -> list[_PlatformEntry]:
        """Load all active DingTalk Bot platforms."""
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Platform.id, Platform.project_id, Platform.api_key, Platform.config)
                    .where(Platform.is_active.is_(True), Platform.type == "dingtalk_bot")
                )
            ).all()
        platforms: list[_PlatformEntry] = []
        for pid, project_id, api_key, cfg_dict in rows:
            try:
                cfg = DingTalkPlatformConfig(**(cfg_dict or {}))
                platforms.append(_PlatformEntry(
                    id=pid,
                    project_id=project_id,
                    api_key=api_key,
                    cfg=cfg,
                ))
            except Exception as e:
                print(f"[DINGTALK] Skip platform {pid}: invalid config: {e}")
        return platforms
    """
        消费者主循环：死循环，直到stop_event被触发
        1.加载全部激活钉钉机器人平台
        2.每个平台处理自己待处理消息
        3.按配置sleep一段时间，继续下一轮轮询
    """
    async def _consumer_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                platforms = await self._load_active_dingtalk_platforms()
                for p in platforms:
                    try:
                        await self._process_pending_for_platform(p)
                    except Exception as e:
                        print(f"[DINGTALK] Consumer error for platform {p.id}: {e}")
                # Sleep using first platform's interval or default
                # 获取轮询间隔；没有平台则默认5秒
                interval = platforms[0].cfg.consumer_poll_interval_seconds if platforms else 5
                await asyncio.sleep(max(1, int(interval)))
            except Exception as e:
                print(f"[DINGTALK] Consumer supervisor error: {e}")
                await asyncio.sleep(5)

    async def _select_candidates(
        self,
        session: AsyncSession,
        platform: _PlatformEntry,
        batch_size: int,
        max_retries: int,
    ) -> list[DingTalkInbox]:
        """Select a batch of candidate records to process for the given platform."""
        # Pending first
        """
        查询一批待处理消息记录
        优先 status=pending 新消息；其次取status=failed，未达到最大重试次数、满足退避时间的失败消息
        with_for_update(skip_locked=True) 行锁，防止多个consumer实例并发重复处理同一条消息
        失败消息采用指数退避：delay = 2^retry_count 秒
        """
        pending = (
            await session.execute(
                select(DingTalkInbox)
                .where(DingTalkInbox.platform_id == platform.id, DingTalkInbox.status == "pending")
                .order_by(DingTalkInbox.fetched_at.asc())
                .with_for_update(skip_locked=True)
                .limit(batch_size)
            )
        ).scalars().all()

        remaining = batch_size - len(pending)
        candidates: list[DingTalkInbox] = list(pending)

        if remaining > 0:
            failed = (
                await session.execute(
                    select(DingTalkInbox)
                    .where(
                        DingTalkInbox.platform_id == platform.id,
                        DingTalkInbox.status == "failed",
                        DingTalkInbox.retry_count < max_retries,
                    )
                    .order_by(DingTalkInbox.processed_at.asc().nullsfirst())
                    .with_for_update(skip_locked=True)
                    .limit(batch_size * 3)
                )
            ).scalars().all()
            now = datetime.now(timezone.utc)
            for record in failed:
                delay = max(1, 2 ** int(record.retry_count or 0))
                if not record.processed_at or (now - record.processed_at).total_seconds() >= delay:
                    candidates.append(record)
                    if len(candidates) >= batch_size:
                        break

        return candidates

    async def _claim_record(self, session: AsyncSession, record: DingTalkInbox) -> bool:
        """Attempt to mark a record as processing. Returns True if claimed successfully."""
        """抢占这条记录：把status修改为processing，标记正在处理；数据库行锁保证多实例不会重复消费"""
        try:
            record.status = "processing"
            record.error_message = None
            await session.commit()
            return True
        except Exception as e:
            print(f"[DINGTALK] Claiming record failed (skip): {e}")
            await session.rollback()
            return False

    def _build_mapped_message(self, platform: _PlatformEntry, record: DingTalkInbox) -> dict[str, Any]:
        """Build the NormalizedMessage-like raw dict for downstream normalization."""
        """
        将DingTalkInbox数据库记录，组装成标准化原始消息字典
        extra里面存放钉钉特有上下文：最重要就是 session_webhook！
        后面分发器内部会读取 extra.dingtalk.session_webhook，实例化 DingTalkBotAdapter 用来回复消息
        """
        raw_payload = record.raw_payload or {}

        # Build DingTalk-specific context used by adapter selection/sending
        dingtalk_ctx: dict[str, Any] = {
            "session_webhook": record.session_webhook or raw_payload.get("session_webhook") or "",
            "conversation_id": record.conversation_id or "",
            "conversation_type": record.conversation_type or "1",
            "sender_nick": record.sender_nick or "",
            "msg_type": record.msg_type,
        }

        return {
            "source": "dingtalk",
            "from_uid": record.from_user,
            "content": record.content or "",
            "platform_api_key": platform.api_key or "",
            "platform_type": "dingtalk_bot",
            "platform_id": str(platform.id),
            "extra": {
                "project_id": str(platform.project_id),
                "msg_type": record.msg_type,
                "dingtalk": dingtalk_ctx,
            },
        }

    async def _get_or_register_visitor(
        self,
        platform: _PlatformEntry,
        record: DingTalkInbox,
    ) -> tuple[Any | None, str | None, str | None]:
        """Visitor retrieval/registration with cache-first approach."""
        """
        获取或注册访客；优先读取Redis缓存，缓存未命中调用接口注册访客
        返回 (visitor对象,昵称,头像地址)
        """
        display_name: str | None = record.sender_nick or record.from_user
        avatar_url: str | None = None
        visitor = None

        # Check cache first
        try:
            cache_key = self._visitor_service.make_cache_key(str(platform.project_id), "dingtalk_bot", record.from_user)
            cached = await self._visitor_service.get_cached(cache_key)
            if cached:
                display_name = cached.nickname or cached.name or display_name
                avatar_url = cached.avatar_url
                return cached, display_name, avatar_url
        except Exception as e:
            print(f"[DINGTALK] Visitor cache lookup failed for {platform.id}: {e}")

        # Register or get visitor via tgo-api
        if platform.api_key:
            try:
                visitor = await self._visitor_service.register_or_get(
                    platform_api_key=platform.api_key,
                    project_id=str(platform.project_id),
                    platform_type="dingtalk_bot",
                    platform_open_id=record.from_user,
                    nickname=display_name,
                    avatar_url=avatar_url,
                )
            except Exception as e:
                print(f"[DINGTALK] Visitor registration failed for {platform.id}: {e}")

        return visitor, display_name, avatar_url
    # """把访客昵称头像，塞进消息extra字段，下游业务可以读取用户资料"""
    def _attach_profile_to_extra(self, mapped_raw: dict[str, Any], display_name: str | None, avatar_url: str | None) -> None:
        """Attach visitor profile fields into mapped_raw.extra.visitor_profile safely."""
        try:
            extra = mapped_raw.get("extra") or {}
            extra["visitor_profile"] = {"nickname": display_name, "avatar_url": avatar_url}
            mapped_raw["extra"] = extra
        except Exception:
            pass
    """处理成功：更新数据库记录状态completed，保存AI回复内容"""        
    async def _finalize_success(self, session: AsyncSession, record: DingTalkInbox, reply_text: str | None) -> None:
        """Mark record as completed with optional reply text."""
        record.ai_reply = reply_text
        record.status = "completed"
        record.processed_at = datetime.now(timezone.utc)
        record.error_message = None
        try:
            await session.commit()
        except Exception as e2:
            print(f"[DINGTALK] Commit completed status failed (ignore): {e2}")
            await session.rollback()
    """处理失败：status改为failed，重试计数+1，保存错误信息；达到max_retry就不再重试"""
    async def _finalize_failure(self, session: AsyncSession, platform: _PlatformEntry, record: DingTalkInbox, error: Exception) -> None:
        """Mark record as failed with retry increment and error message."""
        print(f"[DINGTALK] Processing failed for {platform.id}: {error}")
        record.status = "failed"
        record.processed_at = datetime.now(timezone.utc)
        record.retry_count = int((record.retry_count or 0)) + 1
        record.error_message = str(error)[:2000]
        try:
            await session.commit()
        except Exception as e2:
            print(f"[DINGTALK] Commit failed status failed (ignore): {e2}")
            await session.rollback()
    """单个平台处理一批待处理消息"""
    async def _process_pending_for_platform(self, p: _PlatformEntry) -> None:
        batch_size = max(1, int(getattr(p.cfg, "processing_batch_size", 10) or 10))
        max_retries = max(0, int(getattr(p.cfg, "max_retry_attempts", 3) or 3))

        async with self._session_factory() as db:
            # Select candidate records for this platform (pending + eligible failed)
            candidates: list[DingTalkInbox] = await self._select_candidates(db, p, batch_size, max_retries)
            if not candidates:
                return

            for rec in candidates:
                # Claim record for processing
                if not await self._claim_record(db, rec):
                    continue

                try:
                    # Build mapped message
                    mapped_raw: dict[str, Any] = self._build_mapped_message(p, rec)

                    # Visitor retrieval/registration with cache-first approach
                    visitor, display_name, avatar_url = await self._get_or_register_visitor(p, rec)
                    self._attach_profile_to_extra(mapped_raw, display_name, avatar_url)

                    # Normalize and process
                    msg: NormalizedMessage = await self._normalizer.normalize(mapped_raw)
                    reply_text = await process_message(
                        msg=msg,
                        db=db,
                        tgo_api_client=self._tgo_api_client,
                        sse_manager=self._sse_manager,
                    )

                    # Finalize success
                    await self._finalize_success(db, rec, reply_text)
                except Exception as e:
                    # Finalize failure with retry increment
                    await self._finalize_failure(db, p, rec, e)

