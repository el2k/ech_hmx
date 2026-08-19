from __future__ import annotations
from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.domain.services.normalizer import normalizer
from app.domain.services.dispatcher import process_message
from app.api.schemas import ErrorResponse

router = APIRouter()


@router.post("/ingest", responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def ingest(req: Request, db: AsyncSession = Depends(get_db)) -> dict:
    raw = await req.json()
    msg = await normalizer.normalize(raw)
    tgo_api_client = req.app.state.tgo_api_client
    sse_manager = req.app.state.sse_manager
    await process_message(msg, db, tgo_api_client, sse_manager)
    return {"ok": True}



from typing import Optional
import base64
import hashlib
import logging
import httpx
import uuid

from fastapi import status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.error_utils import error_response, get_request_id
from app.db.models import Platform

from app.api.wecom_utils import wecom_get_access_token, wecom_kf_send_msg, wecom_upload_temp_media, resolve_visitor_platform_open_id, resolve_wecom_open_kfid
from app.api.slack_utils import slack_send_text, slack_send_file, slack_get_dm_channel
from app.core.config import settings

'''业务定位：Docker 容器环境 URL 地址转换工具
外部拿到的 URL 可能是 localhost:8000（宿主机地址），但容器内部不能通过 localhost 访问服务；
这个函数把公网 / 宿主机localhost地址，替换为 docker 集群内部服务地址 settings.api_base_url，让容器内部的代码可以正常请求接口 / 下载资源。'''
def _internalize_url(url: str) -> str:
    """Map public/localhost download URLs to internal Docker service addresses."""
    if not url:
        return url
    
    # If URL is from localhost/api or localhost:8000, map it to internal settings.api_base
      # 获取配置里的容器内部API基地址，去掉末尾斜杠，避免拼接出现 //
    internal_base = settings.api_base_url.rstrip('/')
    
    import re
    # Case1：匹配 http://localhost:8000 或者 http://127.0.0.1:8000 开头的链接
    # 示例：http://localhost:8000/v1/file → 替换成内部地址 http://tgo-api:8080/v1/file
    # Case 1: http://localhost:8000/v1/...
    transformed = re.sub(r'^https?://(localhost|127\.0\.0\.1):8000', internal_base, url)
    # Case 2: http://localhost/api/v1/... -> Strip /api and replace host
    # Case2：处理不带端口的localhost，例如 http://localhost/api/v1/xxx
    # 前端Nginx对外暴露路径是 /api/v1，但是后端内部接口路径是 /v1，需要删掉/api前缀
    if "/api/v1/" in transformed and ("localhost" in transformed or "127.0.0.1" in transformed):
        transformed = transformed.replace("/api/v1/", "/v1/")
        transformed = re.sub(r'^https?://(localhost|127\.0\.0\.1)', internal_base, transformed)
        
    return transformed


class SendMessageRequest(BaseModel):
    platform_api_key: str = Field(..., description="Per-platform API key")
    from_uid: str = Field(..., description="Sender user id (for logging)")
    channel_id: str = Field(..., description="Channel id in format '{visitor_id}-vtr'")
    channel_type: int = Field(..., description="Channel type (e.g., 251)")
    payload: dict = Field(..., description="Message payload (see formats)")
    client_msg_no: Optional[str] = Field(None, description="Client-provided idempotency key")


@router.post(
    "/v1/messages/send",
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
# 对外发送消息统一网关接口
# AI Agent 生成回复之后，调用这个 API，把消息推送到各个第三方 IM 平台。
# 支持平台：custom(自定义回调)、wecom(企业微信客服)、wecom_bot(企业微信群机器人)、email邮件、telegram、slack。
# 入参 SendMessageRequest 里面携带 platform_api_key，用来定位是哪一个平台配置；
# 不是 JWT 登录鉴权，用平台自身的 api_key 做身份认证。
async def send_message(req_body: SendMessageRequest, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Send a message to a third‑party platform (WeCom, Email, etc.).
    向第三方平台发送消息统一出口

    - Auth: 请求体携带 platform_api_key；平台记录必须存在并且启用(is_active=True)
    - channel_id: 格式 '{visitor_id}-vtr'，后端去掉后缀 `-vtr` 得到visitor_id访客ID
    - payload 消息载荷约定：
      * Text: {"type":1, "content":"..."} 文本
      * Image: {"type":2, "url":"http://...", "width":..., "height":...} 图片
    """
    # 获取全链路追踪request_id，所有返回错误都会带上，方便日志排查
    request_id = get_request_id(request)
    # 客户端消息编号，由调用方传入，没有则置空
    client_msg_no = req_body.client_msg_no or ""

    # Lookup platform by api_key
    # ========== 1、鉴权：根据platform_api_key查询平台配置，平台必须激活 ==========
    platform = await db.scalar(select(Platform).where(Platform.api_key == req_body.platform_api_key, Platform.is_active.is_(True)))
    if not platform:
        return error_response(status.HTTP_404_NOT_FOUND, code="PLATFORM_NOT_FOUND", message="Platform not found", request_id=request_id)
     # 平台类型转小写，后续分支判断
    platform_type = (platform.type or "").lower()
    cfg = platform.config or {}

    # Extract visitor_id from channel_id
    # ========== 2、解析访客ID ==========
    channel_id = req_body.channel_id or ""
    # channel_id 如果以 `-vtr`结尾，裁剪后得到visitor_id；否则直接使用原值
    visitor_id = channel_id[:-4] if channel_id.endswith("-vtr") else channel_id

    # Resolve helpers via shared utils (Redis + DB)

    # Validate payload
     # 解析消息体payload
    payload: dict = req_body.payload or {}
    msg_type = int(payload.get("type", 1))

    try:
        # ===================== 分支1：custom 自定义平台 =====================
        # 自定义平台：系统不做实际发送，把完整消息POST转发给用户提供的callback_url，由用户自己实现消息推送
        if platform_type == "custom":
            # Custom platform: forward message to third-party callback URL
            callback_url = (cfg.get("callback_url") or "").strip()
            if not callback_url:
                # 自定义平台必须配置回调地址
                return error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="PLATFORM_CONFIG_INVALID",
                    message="Custom platform requires callback_url in config",
                    request_id=request_id
                )

            # Extract platform_api_key from config (try both field names)
            # 读取配置里的api_key，兼容两个字段名
            platform_api_key_value = cfg.get("platform_api_key") or cfg.get("api_key") or ""

            # Extract platform_open_id from request body
             # 获取第三方平台open_id：优先payload携带，没有则根据visitor_id查表解析
            platform_open_id = req_body.payload.get("platform_open_id") if isinstance(req_body.payload, dict) else None
            if not platform_open_id:
                # Try to resolve from visitor_id if not in payload
                try:
                    platform_open_id = await resolve_visitor_platform_open_id(visitor_id)
                except Exception:
                    platform_open_id = visitor_id  # Fallback to visitor_id

            # Generate unique IDs
            # 生成消息唯一标识
            message_id = str(uuid.uuid4())
            client_msg_no_generated = req_body.client_msg_no or str(uuid.uuid4())

            # Build request payload
            # 组装转发给用户回调接口的数据结构
            custom_payload = {
                "platform_api_key": platform_api_key_value,
                "message_id": message_id,
                "channel_id": req_body.channel_id,
                "channel_type": req_body.channel_type,
                "platform_open_id": platform_open_id,
                "client_msg_no": client_msg_no_generated,
                "payload": req_body.payload,
            }

            # Send POST request to callback URL
            # 异步http POST请求调用用户回调地址
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                response = await client.post(callback_url, json=custom_payload)
                response.raise_for_status() # http非2xx抛异常

            logging.info(
                "[SEND] client_msg_no=%s custom platform message sent to %s",
                client_msg_no_generated,
                callback_url
            )
            return {
                "ok": True,
                "client_msg_no": client_msg_no_generated,
                "message_id": message_id,
                "message": "Message sent successfully to custom platform"
            }
         # ===================== 分支2：wecom 企业微信客服 =====================
        if platform_type == "wecom":
            corp_id = (cfg.get("corp_id") or "").strip()
            app_secret = (cfg.get("app_secret") or "").strip()
            if not (corp_id and app_secret):
                return error_response(status.HTTP_400_BAD_REQUEST, code="PLATFORM_CONFIG_INVALID", message="WeCom requires corp_id and app_secret", request_id=request_id)
             # 获取企业微信access_token（内部有缓存）
            access_token = await wecom_get_access_token(corp_id, app_secret)
            # Resolve destination
             # visitor_id → 企业微信外部用户id
            external_userid = await resolve_visitor_platform_open_id(visitor_id)
            # 解析客服账号open_kfid
            open_kfid = await resolve_wecom_open_kfid(visitor_id, platform.id, db)

            if msg_type == 1:
                # Text
                # 文本消息，截断2048字符，企业微信限制
                content_text = str(payload.get("content") or "")
                await wecom_kf_send_msg(access_token, open_kfid=open_kfid, external_userid=external_userid, msgtype="text", content={"content": content_text[:2048]})
                logging.info("[SEND] client_msg_no=%s wecom text sent to %s", client_msg_no, external_userid)
                return {"ok": True, "client_msg_no": client_msg_no, "message": "Message sent successfully"}
            elif msg_type == 2:
                # Image
                # 图片消息：不能直接传url，要先下载图片，上传企业微信临时素材接口拿到media_id再发送
                url = str(payload.get("url") or "")
                if not url:
                    return error_response(status.HTTP_400_BAD_REQUEST, code="INVALID_PAYLOAD", message="Image url is required", request_id=request_id)
                # Download image
                #👉调用前面讲过的 _internalize_url，把localhost地址转为docker内部可访问地址
                download_url = _internalize_url(url)
                logging.info("[SEND] downloading image for wecom from: %s (original: %s)", download_url, url)
                async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                    r = await client.get(download_url)
                    r.raise_for_status()
                    file_bytes = r.content
                    content_type = r.headers.get("content-type") or "image/jpeg"
                # Derive filename
                # 提取文件名
                try:
                    filename = url.rsplit("/", 1)[-1] or "image.jpg"
                except Exception:
                    filename = "image.jpg"
                # Upload media and send
                 # 上传临时素材，拿到media_id
                media_id = await wecom_upload_temp_media(access_token, file_bytes, media_type="image", filename=filename, content_type=content_type)
                # 使用media_id发送图片消息
                await wecom_kf_send_msg(access_token, open_kfid=open_kfid, external_userid=external_userid, msgtype="image", content={"media_id": media_id})
                logging.info("[SEND] client_msg_no=%s wecom image sent to %s", client_msg_no, external_userid)
                return {"ok": True, "client_msg_no": client_msg_no, "message": "Message sent successfully"}
            else:
                return error_response(status.HTTP_400_BAD_REQUEST, code="UNSUPPORTED_MESSAGE_TYPE", message=f"Unsupported payload type for WeCom: {msg_type}", request_id=request_id)
        # ===================== 分支3：wecom_bot 企业微信群机器人 =====================
        if platform_type == "wecom_bot":
            # WeCom Bot (智能机器人) - direct message sending is not supported
            # Messages can only be sent as replies via response_url from incoming callbacks
            """
            限制：企业微信机器人**不支持主动对外发消息**
            只能作为回调事件的response直接回复，不能调用这个接口主动推送。
            """
            return error_response(
                status.HTTP_400_BAD_REQUEST,
                code="PLATFORM_TYPE_UNSUPPORTED",
                message="WeCom Bot does not support direct message sending. Messages can only be sent as replies to incoming messages.",
                request_id=request_id,
            )
        # ===================== 分支4：email 邮件 =====================
        if platform_type == "email":
            # Resolve target email address for visitor
            target_email = await resolve_visitor_platform_open_id(visitor_id)
            # SMTP config: from per-platform configuration
            smtp_host = cfg.get("smtp_host")
            smtp_port = int(cfg.get("smtp_port", 587))
            smtp_username = cfg.get("smtp_username")
            smtp_password = cfg.get("smtp_password")
            smtp_use_tls = bool(cfg.get("smtp_use_tls", False))
            if not (smtp_host and smtp_port and smtp_username and smtp_password):
                return error_response(status.HTTP_400_BAD_REQUEST, code="PLATFORM_CONFIG_INVALID", message="Email requires SMTP configuration in platform config", request_id=request_id)
            # Only text currently supported via this API
            if msg_type != 1:
                return error_response(status.HTTP_400_BAD_REQUEST, code="UNSUPPORTED_MESSAGE_TYPE", message="Email supports only text (type=1)", request_id=request_id)
            content_text = str(payload.get("content") or "")
            from app.domain.services.adapters.email import EmailAdapter  # local import to avoid circulars
            adapter = EmailAdapter(
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_username=smtp_username,
                smtp_password=smtp_password,
                smtp_use_tls=smtp_use_tls,
                to_addr=target_email,
                from_addr=smtp_username,
                subject="",
            )
            await adapter.send_final({"text": content_text})
            logging.info("[SEND] client_msg_no=%s email sent to %s", client_msg_no, target_email)
            return {"ok": True, "client_msg_no": client_msg_no, "message": "Message sent successfully"}
        # ===================== 分支5：telegram =====================
        if platform_type == "telegram":
            # Get bot token and visitor's chat_id
            bot_token = (cfg.get("bot_token") or "").strip()
            if not bot_token:
                return error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="PLATFORM_CONFIG_INVALID",
                    message="Telegram requires bot_token in config",
                    request_id=request_id,
                )
            
            # Resolve target chat_id for visitor
            chat_id = await resolve_visitor_platform_open_id(visitor_id)
            if not chat_id:
                return error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="VISITOR_NOT_FOUND",
                    message="Could not resolve Telegram chat_id for visitor",
                    request_id=request_id,
                )
            
            if msg_type == 1:
                # Text message
                content_text = str(payload.get("content") or "")
                if not content_text:
                    return error_response(
                        status.HTTP_400_BAD_REQUEST,
                        code="INVALID_PAYLOAD",
                        message="Text content is required",
                        request_id=request_id,
                    )
                
                from app.api.telegram_utils import telegram_send_text
                result = await telegram_send_text(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    text=content_text[:4096],
                )
                
                if result.get("ok"):
                    logging.info("[SEND] client_msg_no=%s telegram text sent to %s", client_msg_no, chat_id)
                    return {"ok": True, "client_msg_no": client_msg_no, "message": "Message sent successfully"}
                else:
                    return error_response(
                        status.HTTP_502_BAD_GATEWAY,
                        code="TELEGRAM_ERROR",
                        message=result.get("description", "Unknown Telegram error"),
                        request_id=request_id,
                    )
            elif msg_type == 2:
                # Image
                url = str(payload.get("url") or "")
                if not url:
                    return error_response(
                        status.HTTP_400_BAD_REQUEST,
                        code="INVALID_PAYLOAD",
                        message="Image url is required",
                        request_id=request_id,
                    )
                
                # Download image first (Telegram servers might not be able to access local URLs)
                try:
                    download_url = _internalize_url(url)
                    logging.info("[SEND] downloading image for telegram from: %s (original: %s)", download_url, url)
                    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                        r = await client.get(download_url)
                        r.raise_for_status()
                        file_bytes = r.content
                except Exception as e:
                    logging.error("[SEND] failed to download image for telegram: %s", e)
                    return error_response(
                        status.HTTP_400_BAD_REQUEST,
                        code="IMAGE_DOWNLOAD_FAILED",
                        message=str(e),
                        request_id=request_id,
                    )
                
                from app.api.telegram_utils import telegram_send_photo
                result = await telegram_send_photo(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    photo=file_bytes,
                )
                
                if result.get("ok"):
                    logging.info("[SEND] client_msg_no=%s telegram photo sent to %s", client_msg_no, chat_id)
                    return {"ok": True, "client_msg_no": client_msg_no, "message": "Message sent successfully"}
                else:
                    return error_response(
                        status.HTTP_502_BAD_GATEWAY,
                        code="TELEGRAM_ERROR",
                        message=result.get("description", "Unknown Telegram error"),
                        request_id=request_id,
                    )
            else:
                return error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="UNSUPPORTED_MESSAGE_TYPE",
                    message=f"Telegram currently supports only text (type=1), got: {msg_type}",
                    request_id=request_id,
                )
        # ===================== 分支6：slack =====================
        if platform_type == "slack":
            # Get bot token and visitor's Slack user ID/channel
            bot_token = (cfg.get("bot_token") or "").strip()
            if not bot_token:
                return error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="PLATFORM_CONFIG_INVALID",
                    message="Slack requires bot_token in config",
                    request_id=request_id,
                )
            
            # Resolve target user_id/channel for visitor
            target_id = await resolve_visitor_platform_open_id(visitor_id)
            if not target_id:
                return error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="VISITOR_NOT_FOUND",
                    message="Could not resolve Slack user_id for visitor",
                    request_id=request_id,
                )
            
            if msg_type == 1:
                # Text message
                content_text = str(payload.get("content") or "")
                if not content_text:
                    return error_response(
                        status.HTTP_400_BAD_REQUEST,
                        code="INVALID_PAYLOAD",
                        message="Text content is required",
                        request_id=request_id,
                    )
                
                result = await slack_send_text(
                    bot_token=bot_token,
                    channel=target_id,
                    text=content_text,
                )
                
                if result.get("ok"):
                    logging.info("[SEND] client_msg_no=%s slack text sent to %s", client_msg_no, target_id)
                    return {"ok": True, "client_msg_no": client_msg_no, "message": "Message sent successfully"}
                else:
                    return error_response(
                        status.HTTP_502_BAD_GATEWAY,
                        code="SLACK_ERROR",
                        message=result.get("error", "Unknown Slack error"),
                        request_id=request_id,
                    )
            elif msg_type == 2:
                # Image
                url = str(payload.get("url") or "")
                if not url:
                    return error_response(
                        status.HTTP_400_BAD_REQUEST,
                        code="INVALID_PAYLOAD",
                        message="Image url is required",
                        request_id=request_id,
                    )
                
                # Download image
                try:
                    download_url = _internalize_url(url)
                    logging.info("[SEND] downloading image for slack from: %s (original: %s)", download_url, url)
                    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                        r = await client.get(download_url)
                        r.raise_for_status()
                        file_bytes = r.content
                except Exception as e:
                    logging.error("[SEND] failed to download image for slack: %s", e)
                    return error_response(
                        status.HTTP_400_BAD_REQUEST,
                        code="IMAGE_DOWNLOAD_FAILED",
                        message=str(e),
                        request_id=request_id,
                    )
                
                # Derive filename
                try:
                    filename = url.rsplit("/", 1)[-1] or "image.png"
                    if "?" in filename:
                        filename = filename.split("?")[0]
                except Exception:
                    filename = "image.png"
                
                # Slack files_upload_v2 requires a real channel ID (starts with D, C, G)
                # If target_id is a User ID (starts with U), resolve it to a DM channel ID
                if target_id.startswith("U"):
                    target_id = await slack_get_dm_channel(bot_token, target_id)

                result = await slack_send_file(
                    bot_token=bot_token,
                    channel=target_id,
                    file_bytes=file_bytes,
                    filename=filename,
                    initial_comment=str(payload.get("content") or ""),
                )
                
                if result.get("ok"):
                    logging.info("[SEND] client_msg_no=%s slack photo sent to %s", client_msg_no, target_id)
                    return {"ok": True, "client_msg_no": client_msg_no, "message": "Message sent successfully"}
                else:
                    return error_response(
                        status.HTTP_502_BAD_GATEWAY,
                        code="SLACK_ERROR",
                        message=result.get("error", "Unknown Slack error"),
                        request_id=request_id,
                    )
            else:
                return error_response(
                    status.HTTP_400_BAD_REQUEST,
                    code="UNSUPPORTED_MESSAGE_TYPE",
                    message=f"Slack supports text(1) and image(2), got: {msg_type}",
                    request_id=request_id,
                )

        return error_response(status.HTTP_400_BAD_REQUEST, code="PLATFORM_TYPE_UNSUPPORTED", message=f"Unsupported platform type: {platform.type}", request_id=request_id)

    except httpx.HTTPStatusError as e:
        logging.error("[SEND] HTTP error: %s", e)
        return error_response(status.HTTP_502_BAD_GATEWAY, code="HTTP_ERROR", message=str(e), request_id=request_id)
    except Exception as e:
        logging.error("[SEND] error: %s", e)
        return error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, code="SEND_FAILED", message=str(e), request_id=request_id)
