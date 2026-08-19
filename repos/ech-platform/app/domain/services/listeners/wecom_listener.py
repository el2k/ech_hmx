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
from app.db.models import Platform, WeComInbox
from app.domain.entities import NormalizedMessage
from app.domain.ports import MessageNormalizer, TgoApiClient, SSEManager
from app.domain.services.dispatcher import process_message
from app.infra.visitor_client import VisitorService
from app.api.wecom_utils import get_wecom_visitor_profile


class WeComPlatformConfig(BaseModel):
    """Per-platform WeCom configuration stored in Platform.config when type='wecom'."""

    corp_id: str = ""     # 企业ID (required for wecom_kf, optional for wecom_bot)
    agent_id: str = ""    # 应用ID (required for wecom_kf, optional for wecom_bot)
    app_secret: str = ""  # 应用密钥 (required for wecom_kf, optional for wecom_bot)
    token: str = ""       # 回调签名 Token
    encoding_aes_key: str | None = None  # 消息加密密钥（可选）

    # Consumer processing configuration
    processing_batch_size: int = 10
    max_retry_attempts: int = 3
    consumer_poll_interval_seconds: int = 5


@dataclass
class _PlatformEntry:
    id: uuid.UUID
    project_id: uuid.UUID
    api_key: str | None
    cfg: WeComPlatformConfig
    platform_type: str  # "wecom" (KF) or "wecom_bot"


class WeComChannelListener:
    """WeCom consumer that processes pending wecom_inbox rows asynchronously.

    Producer: FastAPI callback endpoint stores messages into wecom_inbox.
    Consumer: this listener queries pending rows and processes them via dispatcher.
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

    async def start(self) -> None:
        if self._consumer_task is None or self._consumer_task.done():
            self._consumer_task = asyncio.create_task(self._consumer_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

    async def _load_active_wecom_platforms(self) -> list[_PlatformEntry]:
        """Load all active WeCom platforms (both wecom_kf and wecom_bot types)."""
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Platform.id, Platform.project_id, Platform.api_key, Platform.config, Platform.type)
                    .where(Platform.is_active.is_(True), Platform.type.in_(["wecom", "wecom_bot"]))
                )
            ).all()
        platforms: list[_PlatformEntry] = []
        for pid, project_id, api_key, cfg_dict, platform_type in rows:
            try:
                cfg = WeComPlatformConfig(**(cfg_dict or {}))
                platforms.append(_PlatformEntry(
                    id=pid,
                    project_id=project_id,
                    api_key=api_key,
                    cfg=cfg,
                    platform_type=platform_type or "wecom",
                ))
            except Exception as e:
                print(f"[WECOM] Skip platform {pid}: invalid config: {e}")
        return platforms

    async def _consumer_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                platforms = await self._load_active_wecom_platforms()
                for p in platforms:
                    try:
                        await self._process_pending_for_platform(p)
                    except Exception as e:
                        print(f"[WECOM] Consumer error for platform {p.id}: {e}")
                # Sleep using first platform's interval or default
                interval = platforms[0].cfg.consumer_poll_interval_seconds if platforms else 5
                await asyncio.sleep(max(1, int(interval)))
            except Exception as e:
                print(f"[WECOM] Consumer supervisor error: {e}")
                await asyncio.sleep(5)


    # ---- Internal helper methods (refactor for clarity and reuse) ----
    async def _select_candidates(
        self,
        session: AsyncSession,
        platform: _PlatformEntry,
        batch_size: int,
        max_retries: int,
    ) -> list[WeComInbox]:
        """Select a batch of candidate records to process for the given platform.

        Strategy:
        - Fetch 'pending' first (oldest fetched_at first), FOR UPDATE SKIP LOCKED
        - If under-filled, add eligible 'failed' with exponential backoff, SKIP LOCKED
        """
        # Pending first
        pending = (
            await session.execute(
                select(WeComInbox)
                .where(WeComInbox.platform_id == platform.id, WeComInbox.status == "pending")
                .order_by(WeComInbox.fetched_at.asc())
                .with_for_update(skip_locked=True)
                .limit(batch_size)
            )
        ).scalars().all()

        remaining = batch_size - len(pending)
        candidates: list[WeComInbox] = list(pending)

        if remaining > 0:
            failed = (
                await session.execute(
                    select(WeComInbox)
                    .where(
                        WeComInbox.platform_id == platform.id,
                        WeComInbox.status == "failed",
                        WeComInbox.retry_count < max_retries,
                    )
                    .order_by(WeComInbox.processed_at.asc().nullsfirst())
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

    async def _claim_record(self, session: AsyncSession, record: WeComInbox) -> bool:
        """Attempt to mark a record as processing. Returns True if claimed successfully."""
        try:
            record.status = "processing"
            record.error_message = None
            await session.commit()
            return True
        except Exception as e:
            print(f"[WECOM] Claiming record failed (skip): {e}")
            await session.rollback()
            return False

    def _build_mapped_message(self, platform: _PlatformEntry, record: WeComInbox) -> dict[str, Any]:
        """Build the NormalizedMessage-like raw dict for downstream normalization."""
        # Determine source_type from record or fallback to platform_type
        source_type = getattr(record, "source_type", None) or ("wecom_bot" if platform.platform_type == "wecom_bot" else "wecom_kf")

        # Build WeCom-specific context used by adapter selection/sending
        wecom_ctx: dict[str, Any] = {
            "is_from_colleague": bool(record.is_from_colleague),
            "source_type": source_type,
        }

        if source_type == "wecom_kf":
            # WeCom Customer Service specific context
            try:
                raw_payload = record.raw_payload or {}
                # KF sync messages embed original msg at raw_payload["kf_sync_msg"], which includes open_kfid/external_userid
                kf_msg = raw_payload.get("kf_sync_msg") or {}
                open_kfid = kf_msg.get("open_kfid") or raw_payload.get("open_kfid") or record.open_kfid
                if open_kfid:
                    wecom_ctx["open_kfid"] = open_kfid
            except Exception:
                pass
            # external_userid is needed for KF send; extract via helper
            try:
                wecom_ctx["external_userid"] = self._extract_external_user_id(record)
            except Exception:
                pass
        else:
            # WeCom Bot specific context
            try:
                raw_payload = record.raw_payload or {}
                wecom_ctx["chat_id"] = raw_payload.get("chat_id") or record.open_kfid or ""
                wecom_ctx["chat_type"] = raw_payload.get("chat_type") or ""
                wecom_ctx["aibot_id"] = raw_payload.get("aibot_id") or ""
                # response_url is required for replying to wecom_bot messages
                wecom_ctx["response_url"] = raw_payload.get("response_url") or ""
            except Exception:
                pass

        return {
            "source": "wecom",
            "from_uid": record.from_user,
            "content": record.content or "",
            "platform_api_key": platform.api_key or "",
            "platform_type": platform.platform_type,  # "wecom" or "wecom_bot"
            "platform_id": str(platform.id),
            "extra": {
                "project_id": str(platform.project_id),
                "msg_type": record.msg_type,
                "source_type": source_type,  # "wecom_kf" or "wecom_bot"
                "wecom": wecom_ctx,
            },
        }

    def _extract_external_user_id(self, record: WeComInbox) -> str:
        """Extract external_userid if present in raw_payload; fallback to from_user."""
        try:
            raw_payload = record.raw_payload or {}
            parsed = raw_payload.get("parsed") or {}
            return (
                parsed.get("ExternalUserID")
                or raw_payload.get("external_userid")
                or record.from_user
            )
        except Exception:
            return record.from_user

    async def _fetch_visitor_profile_cached(
        self,
        platform: _PlatformEntry,
        record: WeComInbox,
        external_user_id: str,
    ) -> tuple[str | None, str | None]:
        """Cache-first retrieval of visitor profile; calls WeCom APIs on cache miss."""
        display_name: str | None = None
        avatar_url: str | None = None
        try:
            cache_key = self._visitor_service.make_cache_key(str(platform.project_id), "wecom", record.from_user)
            cached = await self._visitor_service.get_cached(cache_key)
            if cached:
                display_name = cached.nickname or cached.name
                avatar_url = cached.avatar_url
            else:
                profile = await get_wecom_visitor_profile(
                    corp_id=platform.cfg.corp_id,
                    app_secret=platform.cfg.app_secret,
                    external_userid=external_user_id,
                )
                display_name = (profile or {}).get("nickname")
                avatar_url = (profile or {}).get("avatar")
        except Exception as e:
            print(f"[WECOM] Fetch visitor profile failed for {external_user_id}: {e}")
        return display_name, avatar_url

    def _attach_profile_to_extra(self, mapped_raw: dict[str, Any], display_name: str | None, avatar_url: str | None) -> None:
        """Attach visitor profile fields into mapped_raw.extra.visitor_profile safely."""
        try:
            extra = mapped_raw.get("extra") or {}
            extra["visitor_profile"] = {"nickname": display_name, "avatar_url": avatar_url}
            mapped_raw["extra"] = extra
        except Exception:
            pass

    async def _register_visitor(
        self,
        platform: _PlatformEntry,
        record: WeComInbox,
        display_name: str | None,
        avatar_url: str | None,
    ):
        """Register or get visitor through tgo-api, using cache in VisitorService."""
        if not platform.api_key:
            return None
        try:
            return await self._visitor_service.register_or_get(
                platform_api_key=platform.api_key,
                project_id=str(platform.project_id),
                platform_type="wecom",
                platform_open_id=record.from_user,
                nickname=display_name,
                avatar_url=avatar_url,
            )
        except Exception as e:
            print(f"[WECOM] Visitor registration failed for {platform.id}: {e}")
            return None

    async def _finalize_success(self, session: AsyncSession, record: WeComInbox, reply_text: str | None) -> None:
        """Mark record as completed with optional reply text."""
        record.ai_reply = reply_text
        record.status = "completed"
        record.processed_at = datetime.now(timezone.utc)
        record.error_message = None
        try:
            await session.commit()
        except Exception as e2:
            print(f"[WECOM] Commit completed status failed (ignore): {e2}")
            await session.rollback()

    async def _finalize_failure(self, session: AsyncSession, platform: _PlatformEntry, record: WeComInbox, error: Exception) -> None:
        """Mark record as failed with retry increment and error message, preserving logs."""
        print(f"[WECOM] Processing failed for {platform.id}: {error}")
        record.status = "failed"
        record.processed_at = datetime.now(timezone.utc)
        record.retry_count = int((record.retry_count or 0)) + 1
        record.error_message = str(error)[:2000]
        try:
            await session.commit()
        except Exception as e2:
            print(f"[WECOM] Commit failed status failed (ignore): {e2}")
            await session.rollback()

    async def _get_or_register_visitor(
        self,
        platform: _PlatformEntry,
        record: WeComInbox,
    ) -> tuple[Any | None, str | None, str | None]:
        """End-to-end flow for visitor retrieval/registration with minimal calls.

        Steps:
        1) Check VisitorService cache; if exists, return immediately (skip external calls)
        2) Else, fetch profile from WeCom (if possible, only for wecom_kf) to enrich nickname/avatar
        3) Register or get visitor via tgo-api using nickname/avatar; return result
        """
        display_name: str | None = None
        avatar_url: str | None = None
        visitor = None

        # Determine source type for platform-specific handling
        source_type = getattr(record, "source_type", None) or ("wecom_bot" if platform.platform_type == "wecom_bot" else "wecom_kf")
        platform_type_for_visitor = platform.platform_type  # "wecom" or "wecom_bot"

        try:
            cache_key = self._visitor_service.make_cache_key(str(platform.project_id), platform_type_for_visitor, record.from_user)
            cached = await self._visitor_service.get_cached(cache_key)
            if cached:
                display_name = cached.nickname or cached.name
                avatar_url = cached.avatar_url
                return cached, display_name, avatar_url
        except Exception as e:
            # Cache access errors shouldn't stop processing
            print(f"[WECOM] Visitor cache lookup failed for {platform.id}: {e}")

        # Cache miss: try to fetch profile from WeCom to enrich registration
        # Only for wecom_kf (customer service) - wecom_bot doesn't have external contact APIs
        if source_type == "wecom_kf" and platform.cfg.corp_id and platform.cfg.app_secret:
            external_user_id = self._extract_external_user_id(record)
            try:
                profile = await get_wecom_visitor_profile(
                    corp_id=platform.cfg.corp_id,
                    app_secret=platform.cfg.app_secret,
                    external_userid=external_user_id,
                )
                display_name = (profile or {}).get("nickname")
                avatar_url = (profile or {}).get("avatar")
            except Exception as e:
                print(f"[WECOM] Fetch visitor profile failed for {external_user_id}: {e}")
        elif source_type == "wecom_bot":
            # For wecom_bot, try to extract name from raw_payload
            try:
                raw_payload = record.raw_payload or {}
                parsed = raw_payload.get("parsed") or {}
                from_info = parsed.get("from") or {}
                if isinstance(from_info, dict):
                    display_name = from_info.get("name") or from_info.get("alias") or from_info.get("userid")
            except Exception:
                pass

        if platform.api_key:
            try:
                visitor = await self._visitor_service.register_or_get(
                    platform_api_key=platform.api_key,
                    project_id=str(platform.project_id),
                    platform_type=platform_type_for_visitor,
                    platform_open_id=record.from_user,
                    nickname=display_name,
                    avatar_url=avatar_url,
                )
            except Exception as e:
                print(f"[WECOM] Visitor registration failed for {platform.id}: {e}")
        return visitor, display_name, avatar_url


    async def _process_pending_for_platform(self, p: _PlatformEntry) -> None:
        batch_size = max(1, int(getattr(p.cfg, "processing_batch_size", 10) or 10))
        max_retries = max(0, int(getattr(p.cfg, "max_retry_attempts", 3) or 3))

        async with self._session_factory() as db:
            # Select candidate records for this platform (pending + eligible failed)
            candidates: list[WeComInbox] = await self._select_candidates(db, p, batch_size, max_retries)
            if not candidates:
                return

            for rec in candidates:
                # Claim record for processing
                if not await self._claim_record(db, rec):
                    continue

                try:
                    # Build mapped message
                    mapped_raw: dict[str, Any] = self._build_mapped_message(p, rec)

                    # Unified visitor retrieval/registration with cache-first + optional profile
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
