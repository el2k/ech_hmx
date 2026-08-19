"""DingTalk Bot API utilities.

This module provides helper functions for:
- Verifying DingTalk webhook signatures
- Sending messages via sessionWebhook

Docs: https://open.dingtalk.com/document/orgapp/receive-message
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

'''用途：钉钉事件回调接口的签名校验函数
钉钉给你的服务推送事件（消息、审批事件等 webhook 回调）时，HTTP 请求头会带上 timestamp 和 sign；
你的后端用这个函数算出签名，和请求头里的签名对比，确认请求确实来自钉钉，防止伪造请求攻击'''
# app_secret：钉钉应用的密钥，在钉钉开放平台获取，不要对外泄露
# 防止第三方伪造 HTTP 请求调用你的钉钉回调接口。攻击者没有app_secret，无法算出正确签名。
def dingtalk_compute_signature(timestamp: str, app_secret: str) -> str:
    """Compute DingTalk signature for callback verification.

    Signature = Base64(HMAC-SHA256(timestamp + "\\n" + app_secret, app_secret))

    Docs: https://open.dingtalk.com/document/orgapp/configure-event-subcription
    """
    string_to_sign = f"{timestamp}\n{app_secret}"
    hmac_code = hmac.new(
        app_secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def dingtalk_verify_signature(
    timestamp: str,
    sign: str,
    app_secret: str,
) -> bool:
    """
    验证钉钉回调签名。
    计算签名的方式为：Base64(HMAC-SHA256(timestamp + "\\n" + app_secret, app_secret))
    参数:
        timestamp: 来自 X-DingTalk-Timestamp 请求头的时间戳（毫秒）
        sign: 来自 X-DingTalk-Sign 请求头的签名
        app_secret: 来自平台配置的应用密钥
    返回:
        如果签名有效，返回 True；否则返回 False
    """
    if not (timestamp and sign and app_secret):
        return False

    expected = dingtalk_compute_signature(timestamp, app_secret)
    return expected == sign


async def dingtalk_send_webhook(
    session_webhook: str,
    msgtype: str,
    content: Dict[str, Any],
    at: Optional[Dict[str, Any]] = None,
    timeout: Optional[int] = None,
) -> dict:
    """Send a message via DingTalk sessionWebhook.
    通过钉钉sessionWebhook发送消息（应答回调事件）

    官方文档: https://open.dingtalk.com/document/orgapp/the-robot-sends-a-group-message

    Args:
        session_webhook: 钉钉回调消息给到的临时会话webhook地址，一次性/会话级url
        msgtype: 消息类型 (text, markdown, actionCard, feedCard)
        content: 对应类型的消息体字典
        at: 可选，@人的配置，@用户、@所有人

    Returns:
        API返回原始字典

    Raises:
        RuntimeError: 钉钉接口业务报错时抛出异常
    """
     # 参数校验：会话webhook不能为空，没有地址无法发送消息
    if not session_webhook:
        raise RuntimeError("DingTalk sessionWebhook is required")
    # 组装钉钉请求体
    # 钉钉机器人格式：{"msgtype":"text", "text":{"content":"xxx"}, "at": {...}}
    payload: Dict[str, Any] = {
        "msgtype": msgtype,
        msgtype: content,
    }
     # 如果传入@人配置，追加at字段（@指定用户、@all）
    if at:
        payload["at"] = at

    logging.info("[DINGTALK] Sending to webhook: %s, msgtype=%s", session_webhook[:80] + "...", msgtype)
     # 创建异步httpx客户端，超时优先用传入timeout，否则读取项目配置的全局超时
    async with httpx.AsyncClient(timeout=timeout or settings.request_timeout_seconds) as client:
         # POST json请求，把payload作为json body提交给钉钉webhook
        resp = await client.post(session_webhook, json=payload)
        # 如果HTTP状态码4xx/5xx，直接抛出httpx.HTTPStatusError异常
        resp.raise_for_status()
        # 解析响应json
        data = resp.json()
        """
        钉钉成功返回样例：{"errcode": 0, "errmsg": "ok"}
        业务失败 errcode > 0，例如 {"errcode":300001,"errmsg":"sessionWebhook过期"}
        """
        # DingTalk returns {"errcode": 0, "errmsg": "ok"} on success
        errcode = data.get("errcode")
        if errcode not in (0, None):
            raise RuntimeError(f"DingTalk send webhook failed: {data}")

        logging.info("[DINGTALK] Send success: %s", data)
        return data


async def dingtalk_send_text(
    session_webhook: str,
    content: str,
    at_mobiles: Optional[list[str]] = None,
    at_user_ids: Optional[list[str]] = None,
    is_at_all: bool = False,
    timeout: Optional[int] = None,
) -> dict:
    """Convenience wrapper to send text message via DingTalk webhook.

    Args:
        session_webhook: The sessionWebhook URL
        content: Text content
        at_mobiles: List of mobile numbers to @mention
        at_user_ids: List of user IDs to @mention
        is_at_all: Whether to @all members
    """
    text_content = {"content": content}

    at_config = None
    if at_mobiles or at_user_ids or is_at_all:
        at_config = {
            "atMobiles": at_mobiles or [],
            "atUserIds": at_user_ids or [],
            "isAtAll": is_at_all,
        }

    return await dingtalk_send_webhook(
        session_webhook=session_webhook,
        msgtype="text",
        content=text_content,
        at=at_config,
        timeout=timeout,
    )


async def dingtalk_send_markdown(
    session_webhook: str,
    title: str,
    text: str,
    at_mobiles: Optional[list[str]] = None,
    at_user_ids: Optional[list[str]] = None,
    is_at_all: bool = False,
    timeout: Optional[int] = None,
) -> dict:
    """Convenience wrapper to send markdown message via DingTalk webhook.

    Args:
        session_webhook: The sessionWebhook URL
        title: Markdown title (shown in notification)
        text: Markdown content
        at_mobiles: List of mobile numbers to @mention
        at_user_ids: List of user IDs to @mention
        is_at_all: Whether to @all members
    """
    markdown_content = {
        "title": title,
        "text": text,
    }

    at_config = None
    if at_mobiles or at_user_ids or is_at_all:
        at_config = {
            "atMobiles": at_mobiles or [],
            "atUserIds": at_user_ids or [],
            "isAtAll": is_at_all,
        }

    return await dingtalk_send_webhook(
        session_webhook=session_webhook,
        msgtype="markdown",
        content=markdown_content,
        at=at_config,
        timeout=timeout,
    )

