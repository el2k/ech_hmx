from __future__ import annotations

import logging
import json

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.db.models import WeComInbox

try:
    from redis import asyncio as aioredis  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    aioredis = None  # type: ignore


# --- Redis client (lazy singleton) -------------------------------------------------
_redis_client = None


async def get_redis_client():
    """Return a cached Redis asyncio client if configured and healthy; else None."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not aioredis or not settings.redis_url:
        return None
    try:
        _redis_client = aioredis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
        await _redis_client.ping()
        return _redis_client
    except Exception as e:  # pragma: no cover
        logging.warning("[WECOM] Redis unavailable: %s", e)
        return None


# --- WeCom token and API wrappers --------------------------------------------------
async def wecom_get_access_token(corp_id: str, app_secret: str, timeout: Optional[int] = None) -> str:
    """Fetch WeCom access_token.

    Raises RuntimeError if WeCom returns an error.
    """
    url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
    params = {"corpid": corp_id, "corpsecret": app_secret}
    async with httpx.AsyncClient(timeout=timeout or settings.request_timeout_seconds) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom gettoken failed: {data}")
        return data["access_token"]


async def wecom_upload_temp_media(access_token: str, file_bytes: bytes, media_type: str = "image", filename: Optional[str] = None, content_type: Optional[str] = None) -> str:
    """Upload temporary media to WeCom and return media_id.

    Docs: https://developer.work.weixin.qq.com/document/25551
    Endpoint: POST /cgi-bin/media/upload?access_token=ACCESS_TOKEN&type=image
    """
    url = f"https://qyapi.weixin.qq.com/cgi-bin/media/upload?access_token={access_token}&type={media_type}"
    fname = filename or ("upload.jpg" if media_type == "image" else "upload.bin")
    ctype = content_type or ("image/jpeg" if media_type == "image" else "application/octet-stream")
    files = {"media": (fname, file_bytes, ctype)}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        resp = await client.post(url, files=files)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") not in (0, None):
            raise RuntimeError(f"WeCom upload media failed: {data}")
        media_id = data.get("media_id") or data.get("thumb_media_id")
        if not media_id:
            raise RuntimeError(f"WeCom upload media missing media_id: {data}")
        return media_id


async def wecom_kf_sync_msg(access_token: str, open_kf_id: str, cursor: str, event_token: str, limit: int = 500) -> dict:
    """Call KF sync_msg API and return JSON result.

    Required payload params per docs: open_kfid, token; optional: cursor, limit
    See: https://developer.work.weixin.qq.com/document/path/94670
    """
    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={access_token}"
    payload = {
        "open_kfid": open_kf_id,
        "cursor": cursor or "",
        "token": event_token,
        "limit": int(limit),
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()


# --- Visitor profile APIs (KF + ExternalContact) ---------------------------------
from typing import Sequence, Dict, Any


async def _wecom_kf_batch_get_customer_basic(access_token: str, external_userids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Call KF batchget to retrieve basic customer info (nickname, avatar).

    Returns a map: { external_userid: {"nickname": str|None, "avatar": str|None} }
    """
    if not external_userids:
        return {}
    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/customer/batchget?access_token={access_token}"
    payload = {"external_userid_list": list(external_userids)}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
        print("data---->", data)
        if data.get("errcode") != 0:
            raise RuntimeError(f"kf customer batchget failed: {data}")
        result: Dict[str, Dict[str, Any]] = {}
        for item in (data.get("customer_list", []) or []):
            eu = item.get("external_userid")
            if eu:
                result[eu] = {
                    "nickname": item.get("nickname"),
                    "avatar": item.get("avatar"),
                }
        return result


async def _wecom_externalcontact_get(access_token: str, external_userid: str) -> Dict[str, Any] | None:
    """Fallback: Get external contact detail via customer contact API.

    Returns {"name": str|None, "avatar": str|None} or None on failure.
    """
    url = "https://qyapi.weixin.qq.com/cgi-bin/externalcontact/get"
    params = {"access_token": access_token, "external_userid": external_userid}
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        print("_externalcontact_get-data-->", data)
        if data.get("errcode") != 0:
            return None
        ec = data.get("external_contact") or {}
        return {"name": ec.get("name"), "avatar": ec.get("avatar")}


async def get_wecom_visitor_profile(corp_id: str, app_secret: str, external_userid: str) -> Dict[str, str | None]:
    """Fetch WeCom visitor profile (nickname, avatar) for a given external_userid.

    Strategy:
    - Primary: KF batch customer info API
    - Fallback: external contact detail API
    Returns: {"nickname": str|None, "avatar": str|None}
    """
    try:
        access_token = await wecom_get_access_token(corp_id, app_secret)
    except Exception as e:
        # Propagate minimal info: unable to get token -> return empty profile; caller should degrade.
        print(f"[WECOM] get access token failed: {e}")
        return {"nickname": None, "avatar": None}

    # 1) Try KF batchget (works when external_userid belongs to KF contact)
    try:
        basic_map = await _wecom_kf_batch_get_customer_basic(access_token, [external_userid])
        print("basic_map--->", basic_map)
        info = basic_map.get(external_userid)
        if info:
            return {"nickname": info.get("nickname"), "avatar": info.get("avatar")}
    except Exception as e:
        print(f"[WECOM] kf batchget failed for {external_userid}: {e}")

    # 2) Fallback to customer contact detail
    try:
        ec = await _wecom_externalcontact_get(access_token, external_userid)
        if ec:
            return {"nickname": ec.get("name"), "avatar": ec.get("avatar")}
    except Exception as e:
        print(f"[WECOM] externalcontact get failed for {external_userid}: {e}")

    return {"nickname": None, "avatar": None}

# --- KF send message API -----------------------------------------------------------
async def wecom_kf_send_msg(
    access_token: str,
    open_kfid: str,
    external_userid: str,
    msgtype: str,
    content: dict,
) -> dict:
    """Send a KF message to an external user.

    Docs: https://developer.work.weixin.qq.com/document/path/94677
    Required: open_kfid, touser(external_userid), msgtype, specific content block
    Returns JSON response dict; raises on HTTP errors or WeCom errcode != 0.
    """
    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg?access_token={access_token}"
    payload = {
        "open_kfid": open_kfid,
        "touser": external_userid,
        "msgtype": msgtype,
        msgtype: content,
    }
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom KF send_msg failed: {data}")
        return data


async def wecom_kf_send_image_msg(access_token: str, open_kfid: str, external_userid: str, media_id: str) -> dict:
    """Convenience wrapper to send KF image message.

    Equivalent to calling wecom_kf_send_msg(..., msgtype="image", content={"media_id": media_id}).
    """
    return await wecom_kf_send_msg(
        access_token,
        open_kfid=open_kfid,
        external_userid=external_userid,
        msgtype="image",
        content={"media_id": media_id},
    )

# --- WeCom Bot (智能机器人) response API via response_url ----------------------
async def wecom_bot_send_response(
    response_url: str,
    msgtype: str,
    content: dict,
    timeout: Optional[int] = None,
) -> dict:
    """Send a response via WeCom Bot response_url (智能机器人主动回复).

    This is used to reply to messages received by the bot. The response_url
    is provided in the incoming message callback.

    Docs: https://developer.work.weixin.qq.com/document/path/101138

    IMPORTANT: The 主动回复消息 API only supports:
    - markdown: {"content": "消息内容"}
    - template_card: {...}

    NOTE: "text" message type is NOT supported by this API!
    Use "markdown" for plain text responses.

    Returns JSON response dict; raises on HTTP errors or WeCom errcode != 0.
    """
    if not response_url:
        raise RuntimeError("WeCom Bot response_url is required")

    payload: Dict[str, Any] = {
        "msgtype": msgtype,
        msgtype: content,
    }

    logging.info("[WECOM_BOT] Sending response to %s, payload=%s", response_url[:80] + "...", json.dumps(payload, ensure_ascii=False)[:200])

    async with httpx.AsyncClient(timeout=timeout or settings.request_timeout_seconds) as client:
        resp = await client.post(response_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        logging.info("[WECOM_BOT] Response result: %s", data)
        if data.get("errcode") not in (0, None):
            raise RuntimeError(f"WeCom Bot response failed: {data}")
        return data


async def wecom_bot_send_response_text(
    response_url: str,
    content: str,
    timeout: Optional[int] = None,
) -> dict:
    """Send text response via WeCom Bot response_url (using markdown format).

    Docs: https://developer.work.weixin.qq.com/document/path/101138

    NOTE: The 主动回复消息 API does NOT support "text" type!
    We use "markdown" type to send plain text responses.

    Args:
        response_url: The response URL from the incoming message
        content: Message text content (max 20480 bytes)
    """
    # Use markdown type since text type is not supported by 主动回复消息 API
    return await wecom_bot_send_response(response_url, msgtype="markdown", content={"content": content[:20480]}, timeout=timeout)


async def wecom_bot_send_response_markdown(
    response_url: str,
    content: str,
    timeout: Optional[int] = None,
) -> dict:
    """Send markdown response via WeCom Bot response_url.

    Docs: https://developer.work.weixin.qq.com/document/path/101138

    Args:
        response_url: The response URL from the incoming message
        content: Markdown content (max 20480 bytes)
    """
    return await wecom_bot_send_response(response_url, msgtype="markdown", content={"content": content[:20480]}, timeout=timeout)


# --- App (colleague) send message API -----------------------------------------
async def wecom_send_app_message(
    access_token: str,
    to_user: str,
    agent_id: int | str,
    msgtype: str,
    content: dict,
    duplicate_check_interval: int | None = 10,
    timeout: Optional[int] = None,
) -> dict:
    """Send an application message to an internal colleague (enterprise member).

    Docs: https://developer.work.weixin.qq.com/document/path/90236
    Endpoint: POST /cgi-bin/message/send
    Raises RuntimeError when WeCom errcode != 0.
    """
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
    payload: Dict[str, Any] = {
        "touser": to_user,
        "agentid": int(agent_id),
        "msgtype": msgtype,
        msgtype: content,
    }
    if duplicate_check_interval is not None:
        payload["duplicate_check_interval"] = int(duplicate_check_interval)

    async with httpx.AsyncClient(timeout=timeout or settings.request_timeout_seconds) as client:
        resp = await client.post(url, content=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"WeCom app send message failed: {data}")
        return data




# --- Visitor/platform resolution helpers -----------------------------------------
async def resolve_visitor_platform_open_id(visitor_id: str) -> str:
    """Resolve a tgo-platform visitor_id to the platform-specific open ID with Redis caching.

    Cache key: visitor:{visitor_id}:platform_open_id
    Fetches from tgo-api GET /v1/visitors/{visitor_id}/basic on cache miss.
    """
    vid = (visitor_id or "").strip()
    if not vid:
        raise RuntimeError("Missing visitor_id to resolve platform_open_id")
    key = f"visitor:{vid}:platform_open_id"
    redis = await get_redis_client()
    if redis:
        try:
            cached = await redis.get(key)
            if cached:
                return cached
        except Exception as e:
            logging.warning("[RESOLVE] Redis get failed for %s: %s", key, e)
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=settings.request_timeout_seconds) as client:
        resp = await client.get(f"/v1/visitors/{vid}/basic")
        resp.raise_for_status()
        data = resp.json()
    platform_open_id = (data or {}).get("platform_open_id") or ""
    if not platform_open_id:
        raise RuntimeError("Visitor basic info missing platform_open_id")
    if redis:
        try:
            await redis.set(key, platform_open_id, ex=3600)
        except Exception as e:
            logging.warning("[RESOLVE] Redis set failed for %s: %s", key, e)
    return platform_open_id


async def resolve_wecom_open_kfid(visitor_id: str, platform_id, db: AsyncSession) -> str:
    """Resolve WeCom open_kfid for a visitor on a platform with Redis caching.

    Cache key: wecom:visitor:{visitor_id}:open_kfid
    Looks up latest WeComInbox for (platform_id, from_user == platform_open_id).
    """
    vid = (visitor_id or "").strip()
    if not vid or platform_id is None:
        raise RuntimeError("Missing visitor_id or platform_id to resolve open_kfid")

    cache_key = f"wecom:visitor:{vid}:open_kfid"
    redis = await get_redis_client()
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return cached
        except Exception as e:
            logging.warning("[RESOLVE] Redis get failed for %s: %s", cache_key, e)

    platform_open_id = await resolve_visitor_platform_open_id(vid)

    stmt = (
        select(WeComInbox.open_kfid)
        .where(WeComInbox.platform_id == platform_id, WeComInbox.from_user == platform_open_id)
        .order_by(WeComInbox.received_at.desc(), WeComInbox.fetched_at.desc())
        .limit(1)
    )
    row = await db.execute(stmt)
    r = row.first()
    if not r or not (r[0] or "").strip():
        raise RuntimeError("No WeCom KF conversation found for visitor; cannot resolve open_kfid")

    open_kfid = str(r[0]).strip()
    if redis:
        try:
            await redis.set(cache_key, open_kfid, ex=3600)
        except Exception as e:
            logging.warning("[RESOLVE] Redis set failed for %s: %s", cache_key, e)
    return open_kfid


# --- Shared helpers ---------------------------------------------------------------
def build_xml_raw_payload(raw_xml: str, decrypted_xml: Optional[str], parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Construct a standardized raw_payload for XML-based webhooks."""
    payload: Dict[str, Any] = {"raw_xml": raw_xml}
    if decrypted_xml is not None:
        payload["decrypted_xml"] = decrypted_xml
    payload["parsed"] = parsed
    return payload


async def try_store_wecom_inbox(db: AsyncSession, **kwargs) -> bool:
    """Persist a WeComInbox row. Returns True if stored, False if duplicate or failed."""
    try:
        rec = WeComInbox(**kwargs)
        db.add(rec)
        await db.commit()
        return True
    except IntegrityError:
        await db.rollback()
        return False
    except Exception as e:  # pragma: no cover
        await db.rollback()
        logging.error("[WECOM] Failed to store inbox record: %s", e)
        return False


def _extract_kf_content(msg: Dict[str, Any]) -> Tuple[str, str, str, Optional[datetime]]:
    """Extract minimal fields from a KF message for inbox storage.

    Returns a tuple: (external_userid, msgtype, content_text, received_at)
    Content text is a readable placeholder for non-text types.
    """
    msgtype = str(msg.get("msgtype") or "unknown")
    external_userid = str(msg.get("external_userid") or "")
    send_time = int(msg.get("send_time") or 0)
    received_at = None
    try:
        if send_time > 0:
            received_at = datetime.fromtimestamp(send_time, tz=timezone.utc)
    except Exception:  # pragma: no cover
        received_at = None

    # Rich content extraction for common types
    content = ""
    if msgtype == "text":
        content = ((msg.get("text") or {}).get("content") or "")
    elif msgtype == "image":
        media_id = ((msg.get("image") or {}).get("media_id") or "")
        content = f"[image]{' ' + media_id if media_id else ''}"
    elif msgtype == "file":
        file_obj = (msg.get("file") or {})
        name = file_obj.get("file_name") or ""
        size = file_obj.get("file_size")
        size_str = f" ({size}B)" if isinstance(size, int) else ""
        content = f"[file]{' ' + name if name else ''}{size_str}"
    elif msgtype == "video":
        media_id = ((msg.get("video") or {}).get("media_id") or "")
        content = f"[video]{' ' + media_id if media_id else ''}"
    elif msgtype == "voice":
        media_id = ((msg.get("voice") or {}).get("media_id") or "")
        content = f"[voice]{' ' + media_id if media_id else ''}"
    elif msgtype == "link":
        link = (msg.get("link") or {})
        title = link.get("title") or ""
        url = link.get("url") or ""
        content = f"[link]{' ' + title if title else ''}{' ' + url if url else ''}"
    else:
        # Fallback placeholder for other types (location, event, etc.)
        content = f"[{msgtype}]"

    return external_userid, msgtype, content, received_at


# --- KF sync driver ---------------------------------------------------------------
async def sync_kf_messages(
    corp_id: str,
    app_secret: str,
    event_token: str,
    open_kf_id: str,
    platform_id,
    db: AsyncSession,
    *,
    max_iters: int = 10,
    cursor_ttl_seconds: int = 7 * 24 * 60 * 60,
    batch_limit: int = 500,
) -> None:
    """Sync actual KF messages upon receiving kf_msg_or_event.

    - Manages cursor in Redis: wecom:kf:cursor:{corp_id}:{open_kf_id}
    - Paginates until has_more == 0 or max_iters reached
    - Stores each message into wecom_inbox with enriched content placeholder
    - Logs metrics per page
    """
    # Token
    try:
        access_token = await wecom_get_access_token(corp_id, app_secret)
    except Exception as e:
        logging.error("[WECOM] KF sync: failed to get access token: %s", e)
        return

    # Cursor
    cursor_key = f"wecom:kf:cursor:{corp_id}:{open_kf_id}".lower()
    redis = await get_redis_client()
    cursor = ""
    if redis:
        try:
            cursor = await redis.get(cursor_key) or ""
        except Exception as e:
            logging.warning("[WECOM] KF sync: redis get cursor failed: %s", e)

    for page in range(1, max_iters + 1):
        # Call sync
        try:
            data = await wecom_kf_sync_msg(access_token, open_kf_id, cursor, event_token=event_token, limit=batch_limit)
        except Exception as e:
            logging.error("[WECOM] KF sync: sync_msg call failed (open_kfid=%s): %s", open_kf_id, e)
            break

        if data.get("errcode") not in (0, None):
            logging.error("[WECOM] KF sync: API returned error: %s", data)
            break

        msg_list = data.get("msg_list") or []
        stored_count = 0
        for msg in msg_list:
            if not isinstance(msg, dict):
                continue
            msgid = str(msg.get("msgid") or "")
            if not msgid:
                continue  # no idempotency key
            ext_uid, msgtype, content, received_at = _extract_kf_content(msg)
            stored = await try_store_wecom_inbox(
                db,
                platform_id=platform_id,
                message_id=msgid,
                source_type="wecom_kf",  # WeCom Customer Service (客服)
                from_user=ext_uid or "",
                open_kfid=open_kf_id,
                msg_type=msgtype,
                content=content,
                is_from_colleague=False,
                raw_payload={"kf_sync_token": event_token, "kf_sync_msg": msg},
                status="pending",
                received_at=received_at,
            )
            if stored:
                stored_count += 1

        # Update cursor and metrics
        cursor = data.get("next_cursor") or cursor
        if redis and cursor is not None:
            try:
                await redis.set(cursor_key, cursor, ex=cursor_ttl_seconds)
            except Exception as e:
                logging.warning("[WECOM] KF sync: redis set cursor failed: %s", e)

        has_more = int(data.get("has_more") or 0)
        logging.info(
            "[WECOM] KF sync page=%s fetched=%s stored=%s has_more=%s",
            page,
            len(msg_list),
            stored_count,
            has_more,
        )
        if not has_more:
            break

