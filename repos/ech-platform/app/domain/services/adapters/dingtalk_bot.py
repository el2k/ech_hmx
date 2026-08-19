"""DingTalk Bot outbound adapter.

Sends messages to DingTalk using the sessionWebhook.
"""
from __future__ import annotations

from app.domain.entities import StreamEvent
from app.domain.services.adapters.base import BasePlatformAdapter
from app.core.config import settings

from app.api.dingtalk_utils import dingtalk_send_text

# 这是向外发送消息的适配器类，继承 BasePlatformAdapter，专门处理钉钉机器人消息回复
# DingTalkBotAdapter：回调事件内即时回复，使用钉钉回调给的临时 session_webhook；只用于应答本次用户触发的事件，不能主动外发消息。
class DingTalkBotAdapter(BasePlatformAdapter):
    """Outbound adapter for DingTalk Bot (钉钉机器人).

    - Non-streaming: sends the final aggregated content via sessionWebhook
    - Uses session_webhook from callback message to reply (required)

    Docs:
    - Robot messages: https://open.dingtalk.com/document/orgapp/the-robot-sends-a-group-message
    """
    # 不支持流式分片输出；钉钉机器人没有SSE/分片消息能力，只能一次性发完整文本
    supports_stream = False

    def __init__(
        self,
        session_webhook: str,
        http_timeout: int | None = None,
    ) -> None:
        #  钉钉回调事件给到的临时会话webhook，短期有效，只能用来回复本次会话
        self.session_webhook = session_webhook  # Required for replying
        # http超时，优先传入值，否则取全局settings配置
        self.http_timeout = http_timeout or settings.request_timeout_seconds

    async def send_incremental(self, ev: StreamEvent) -> None:
        """
                流式增量输出回调；
                supports_stream=False，钉钉不支持逐片推送，所以直接忽略每一块流式事件。
                Agent流式生成的中间片段全部丢弃，等全部生成完毕调用 send_final。
        """
        # DingTalk Bot adapter does not support streaming output; ignore incremental events
        return
    # """Agent全部生成完成，发送最终完整文本给钉钉用户"""
    async def send_final(self, content: dict) -> None:
        
        text = (content or {}).get("text") or ""
        if not text:
            # Nothing to send
            return

        if not self.session_webhook:
            raise RuntimeError("DingTalk Bot adapter requires session_webhook")

        # Send text message via sessionWebhook
        await dingtalk_send_text(
            session_webhook=self.session_webhook,
            content=text[:20000],  # DingTalk text limit
            timeout=self.http_timeout,
        )
'''
用户在钉钉群 @机器人发消息 → 钉钉 HTTP 回调请求打到项目 webhook 接口
请求体里面携带 sessionWebhook
后端构造 DingTalkBotAdapter(session_webhook=xxx)
启动 Agent，Agent 一边流式生成，一边调用 adapter.send_incremental()，适配器直接忽略
Agent 生成全部结束，调用 adapter.send_final({"text":"完整回答"})
内部调用 dingtalk_send_text() POST 请求 sessionWebhook，消息回复到钉钉群'''

