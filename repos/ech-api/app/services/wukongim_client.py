"""WuKongIM client for instant messaging integration."""
# 模块功能：即时通讯服务 WuKongIM 的客户端封装，用于业务系统与 IM 服务的集成

# ========== 标准库导入 ==========
import base64          # Base64 编解码，WuKongIM 消息 payload 统一用 base64 传输
import binascii        # 捕获 base64 解码异常
from datetime import datetime
import json            # JSON 序列化/反序列化
import logging         # 日志模块
from typing import Any, Dict, List, Optional  # 类型注解
from uuid import uuid4  # 生成唯一消息ID，用于 client_msg_no 幂等关联

# ========== 第三方库导入 ==========
import httpx           # 异步 HTTP 客户端，用于调用 WuKongIM 服务端 API
from fastapi import HTTPException  # FastAPI 异常类，统一向上抛出 HTTP 错误

# ========== 项目内部导入 ==========
from app.core.config import settings  # 全局配置，读取 IM 服务地址、超时、开关等配置
from app.utils.const import MessageType  # 消息类型常量（文本、系统通知等）
from app.schemas.wukongim import (  # Pydantic 响应模型，类型安全地封装接口返回数据
    WuKongIMRouteResponse,
    WuKongIMMessageSendResponse,
    WuKongIMChannelLastMessage,
    WuKongIMConversation,
    WuKongIMChannelMessageSyncResponse,
    WuKongIMMessage,
    WuKongIMSearchMessagesResponse,
    WuKongIMSearchResult,
    WuKongIMOnlineStatusItem,
)

# 初始化当前模块日志器
logger = logging.getLogger(__name__)

class EventType:
    """WuKongIM event type constants.
    
    自定义业务事件类型常量，用于通过 IM 通道发送业务通知事件，
    接收端根据事件类型执行对应的前端刷新/业务逻辑。
    
    Event types for real-time notifications:
        - VISITOR_PROFILE_UPDATED: 访客资料更新事件（标签、AI洞察等变化）
        - QUEUE_UPDATED: 排队队列更新事件（新访客进入排队）
    """
    VISITOR_PROFILE_UPDATED = "visitor.profile.updated"
    QUEUE_UPDATED = "queue.updated"

class WuKongIMClient:
    """Client for WuKongIM instant messaging service.
    
    封装所有与 WuKongIM 服务端交互的 HTTP API，提供业务层可直接调用的方法。
    所有方法均为异步实现，内置服务开关、统一异常处理、日志埋点。
    """

    def __init__(self) -> None:
        """Initialize WuKongIM client.
        
        从配置文件初始化客户端参数：
        - 服务地址自动去除末尾斜杠，避免拼接路径时双斜杠
        - 请求超时时间
        - 服务总开关，支持全局禁用 IM 集成
        """
        self.base_url = settings.WUKONGIM_SERVICE_URL.rstrip("/")
        self.timeout = settings.WUKONGIM_SERVICE_TIMEOUT
        self.enabled = settings.WUKONGIM_ENABLED
    def _decode_message_payload(self, payload: str) -> Dict[str, Any]:
        """
        将 WuKongIM 返回的 base64 编码消息体，解码为结构化 JSON 对象。
        多层异常兜底：解码失败时不会崩溃，而是返回带错误标识的结构化数据。

        Args:
            payload: Base64 编码的消息内容字符串

        Returns:
            解码后的 JSON 字典；解码失败时返回包含 raw_payload 和错误类型的字典
        """
        try:
            # 第一步：base64 解码 → UTF-8 字符串
            decoded_bytes = base64.b64decode(payload)
            decoded_str = decoded_bytes.decode('utf-8')
            # 第二步：归一化解码（处理嵌套编码、SDK 特殊格式等）
            json_payload = self._normalize_decoded_payload(
                decoded_str,
                raw_payload=payload,
            )

            logger.debug("Successfully decoded message payload")
            return json_payload

        # 捕获 base64 格式错误、UTF-8 编码错误
        except (binascii.Error, UnicodeDecodeError) as e:
            logger.warning(f"Failed to decode base64 payload: {e}")
            # 兜底：返回原始 payload + 错误类型，不中断主流程
            return {
                "raw_payload": payload,
                "decode_error": "base64_decode_failed",
            }

        # 捕获 JSON 解析失败（解码后不是合法 JSON）
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from decoded payload: {e}")
            # 二次尝试：重新解码并返回纯文本内容
            try:
                decoded_str = base64.b64decode(payload).decode('utf-8')
                return {
                    "raw_content": decoded_str,
                    "decode_error": "json_parse_failed",
                }
            except Exception:
                # 完全解码失败兜底
                return {
                    "raw_payload": payload,
                    "decode_error": "complete_decode_failed",
                }

        # 其他未知异常兜底
        except Exception as e:
            logger.error(f"Unexpected error decoding payload: {e}")
            return {"raw_payload": payload, "decode_error": "unexpected_error"}
    def _normalize_decoded_payload(
        self,
        decoded_payload: str,
        *,
        raw_payload: str,
    ) -> Dict[str, Any]:
        """归一化处理 WuKongIM 混合编码的 payload，最终输出标准 JSON 对象。
        
        背景兼容：
        - HTTP 接口直接发送的消息：一层 base64 → JSON
        - SDK 端发送的消息：可能存在 JSON 套 base64 再套 JSON 的多层嵌套
        设计：最多循环 4 次尝试解码，防止恶意构造的无限嵌套导致死循环。
        """
        current: object = decoded_payload

        # 最多尝试 4 层嵌套解码
        for _ in range(4):
            # 已经是字典，直接返回
            if isinstance(current, dict):
                return current

            # 不是字符串也不是字典，类型不支持
            if not isinstance(current, str):
                return {
                    "raw_payload": raw_payload,
                    "decode_error": "unsupported_payload_type",
                }

            # 第一步尝试：把字符串当 JSON 解析
            try:
                parsed_payload = json.loads(current)
            except json.JSONDecodeError:
                parsed_payload = None

            # 解析出字典，直接返回
            if isinstance(parsed_payload, dict):
                return parsed_payload
            # 解析出还是字符串，继续下一轮循环（可能是嵌套的 base64）
            if isinstance(parsed_payload, str):
                current = parsed_payload
                continue

            # JSON 解析失败，尝试 base64 再解码一层
            try:
                current = base64.b64decode(current).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                return {
                    "raw_content": current,
                    "decode_error": "json_parse_failed",
                }

        # 4 次循环后还是字符串，解析失败
        if isinstance(current, str):
            return {
                "raw_content": current,
                "decode_error": "json_parse_failed",
            }

        return {
            "raw_payload": raw_payload,
            "decode_error": "unsupported_payload_type",
        }
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """统一封装 WuKongIM HTTP 请求。
        
        所有对外方法最终都会调用此方法发请求，统一处理：
        1. 服务开关校验
        2. URL 拼接
        3. 超时、网络异常处理
        4. 响应状态码校验、错误统一转换为 FastAPI HTTPException
        5. 空响应体兼容

        Args:
            method: HTTP 方法（GET/POST 等）
            endpoint: 接口路径，如 /message/send
            json_data: POST 请求的 JSON Body
            params: GET 请求的查询参数

        Returns:
            接口返回的 JSON 字典；空响应返回空字典
        """
        # 服务未启用，直接返回空字典，不发请求
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled, skipping request")
            return {}

        # 拼接完整请求 URL
        url = f"{self.base_url}{endpoint}"

        logger.debug(f"WuKongIM request: {method} {url}")

        try:
            # 创建异步 httpx 客户端，设置超时
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    json=json_data,
                    params=params,
                )

            logger.debug(f"WuKongIM response: {response.status_code}")

            # WuKongIM 约定：200 为成功
            if response.status_code == 200:
                # 部分接口成功时返回空 body，兼容处理
                try:
                    return response.json() if response.text else {}
                except Exception:
                    return {}
            else:
                # 错误响应：尝试解析错误信息
                try:
                    error_data = response.json()
                    error_msg = error_data.get("msg", f"WuKongIM error: {response.status_code}")
                except Exception:
                    error_msg = f"WuKongIM HTTP error: {response.status_code}"

                logger.error(f"WuKongIM error response: {response.status_code} - {error_msg}")
                # 统一向上抛出 500 错误
                raise HTTPException(
                    status_code=500,
                    detail=f"WuKongIM service error: {error_msg}"
                )

        # 超时异常
        except httpx.TimeoutException:
            logger.error(f"WuKongIM request timeout: {method} {url}")
            raise HTTPException(
                status_code=500,
                detail="WuKongIM service timeout"
            )
        # 网络连接异常（DNS 失败、连接拒绝等）
        except httpx.RequestError as e:
            logger.error(f"WuKongIM request error: {e}")
            raise HTTPException(
                status_code=500,
                detail="WuKongIM service unavailable"
            )
    async def send_event(
        self,
        *,
        channel_id: str,
        channel_type: int,
        event_type: str,
        data: Any,
        client_msg_no: Optional[str] = None,
        from_uid: Optional[str] = None,
        force: bool = True,
    ) -> Optional[WuKongIMMessageSendResponse]:
        """以命令消息（type=99）的形式发送自定义业务事件。
        
        事件消息特性：不持久化、不触发红点、仅同步一次，适合纯业务通知场景，
        不会出现在聊天历史记录里，仅用于实时触发前端逻辑。

        Args:
            channel_id: 频道 ID
            channel_type: 频道类型
            event_type: 事件类型字符串（见 EventType 常量）
            data: 事件携带的业务数据
            client_msg_no: 客户端消息号，用于幂等
            from_uid: 发送方 UID
            force: 是否强制推送
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_event")
            return None

        logger.debug(
            "Sending WuKongIM event as command message",
            extra={
                "from_uid": from_uid,
                "channel_id": channel_id,
                "event_type": event_type,
                "force": force,
            },
        )

        # WuKongIM 命令消息格式：type=99 代表自定义命令
        payload: Dict[str, Any] = {
            "type": 99,
            "cmd": event_type,   # 命令名即事件类型
            "param": data if data is not None else {},  # 事件参数
        }

        # 复用底层发消息方法，设置事件消息的专属属性
        return await self.send_message(
            payload=payload,
            from_uid=from_uid,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=client_msg_no,
            no_persist=True,     # 不持久化，不存历史消息
            red_dot=False,       # 不触发未读红点
            sync_once=True,      # 仅同步一次，离线用户不会再收到
        )
    
    async def send_stream_message(
        self,
        *,
        from_uid: str,
        channel_id: str,
        channel_type: int,
        client_msg_no: str,
        payload: Dict[str, Any],
    ) -> Optional[WuKongIMMessageSendResponse]:
        """发送流式消息锚点（创建流式消息的根消息）。
        
        AI 流式回复场景：先发一条 is_stream=1 的锚点消息占位，
        后续通过 stream event 持续追加内容，最终形成完整回复。
        """
        return await self.send_message(
            payload=payload,
            from_uid=from_uid,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=client_msg_no,
            is_stream=1,  # 标记为流式消息锚点
        )
    async def send_stream_event(
        self,
        *,
        channel_id: str,
        channel_type: int,
        client_msg_no: str,
        event_id: str,
        event_type: str,
        event_key: str = "main",
        from_uid: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """发送流式消息事件，对应 /message/event 接口。
        
        用于 AI 流式输出场景，持续向锚点消息追加内容、控制流状态。

        Args:
            channel_id: 频道 ID
            channel_type: 频道类型
            client_msg_no: 锚点消息的客户端消息号，用于关联
            event_id: 事件唯一 ID，用于幂等去重
            event_type: 流事件类型：stream.delta(增量内容) / stream.close / stream.finish / stream.error / stream.cancel
            event_key: 事件通道键，支持 main(主内容)、thinking(思考过程)、tool:* (工具调用) 等多路流
            from_uid: 发送方 UID
            payload: 事件负载，比如增量文本内容
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_stream_event")
            return {}

        # 组装请求参数
        request_data: Dict[str, Any] = {
            "channel_id": channel_id,
            "channel_type": channel_type,
            "client_msg_no": client_msg_no,
            "event_id": event_id,
            "event_type": event_type,
            "event_key": event_key,
        }
        # 可选参数按需添加
        if from_uid:
            request_data["from_uid"] = from_uid
        if payload is not None:
            request_data["payload"] = payload

        logger.debug(
            "Sending WuKongIM stream event",
            extra={
                "channel_id": channel_id,
                "event_type": event_type,
                "event_key": event_key,
                "client_msg_no": client_msg_no,
            },
        )

        return await self._make_request(
            method="POST",
            endpoint="/message/event",
            json_data=request_data,
        )    
    async def send_message(
        self,
        *,
        payload: Dict[str, Any],
        from_uid: Optional[str] = None,
        channel_id: Optional[str] = None,
        channel_type: Optional[int] = None,
        client_msg_no: Optional[str] = None,
        subscribers: Optional[List[str]] = None,
        no_persist: bool = False,
        red_dot: bool = True,
        sync_once: bool = False,
        is_stream: int = 0,
    ) -> Optional[WuKongIMMessageSendResponse]:
        """通用发消息底层方法，直接映射 WuKongIM /message/send API。
        
        所有发消息类方法最终都会调用此方法。业务层优先使用上层便捷方法。

        Args:
            payload: 消息内容字典，内部会自动做 JSON + base64 编码
            from_uid: 发送方 UID
            channel_id: 接收频道 ID
            channel_type: 频道类型（1=私聊 2=群聊 251=客服频道）
            client_msg_no: 客户端消息唯一标识，用于幂等、回调关联
            subscribers: 指定接收者列表，可实现定向推送
            no_persist: 是否不持久化消息（默认 False=持久化存历史）
            red_dot: 是否触发未读红点（默认 True=触发）
            sync_once: 是否仅同步一次（默认 False=离线用户上线仍能收到）
            is_stream: 是否流式锚点消息（0=普通 1=流式锚点）

        Returns:
            发送响应，包含 message_id、message_seq、client_msg_no；服务禁用返回 None
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_message")
            return None

        # WuKongIM 要求 payload 必须是 base64 编码的 JSON 字符串
        payload_encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

        request_data: Dict[str, Any] = {
            "payload": payload_encoded,
        }

        # 可选参数：有值才加入请求体
        if from_uid is not None:
            request_data["from_uid"] = from_uid
        if channel_id is not None:
            request_data["channel_id"] = channel_id
        if channel_type is not None:
            request_data["channel_type"] = channel_type
        if client_msg_no is not None:
            request_data["client_msg_no"] = client_msg_no
        if subscribers is not None:
            request_data["subscribers"] = subscribers
        if is_stream:
            request_data["is_stream"] = is_stream

        # 消息头控制参数：非默认值才组装 header
        header: Dict[str, int] = {}
        if no_persist:
            header["no_persist"] = 1
        if not red_dot:
            header["red_dot"] = 0
        if sync_once:
            header["sync_once"] = 1
        if header:
            request_data["header"] = header

        logger.info(
            "Sending WuKongIM message",
            extra={
                "from_uid": from_uid,
                "channel_id": channel_id,
                "channel_type": channel_type,
                "client_msg_no": client_msg_no,
                "has_subscribers": subscribers is not None,
            }
        )

        result = await self._make_request(
            method="POST",
            endpoint="/message/send",
            json_data=request_data,
        )
        logger.debug("WuKongIM send_message result: %s", result)
        
        # WuKongIM 响应格式：{"status":200, "data": {...}}，提取 data 字段转成 Pydantic 模型
        if result and "data" in result:
            return WuKongIMMessageSendResponse(**result["data"])
        return None
    async def send_text_message(
        self,
        *,
        from_uid: str,
        channel_id: str,
        channel_type: int,
        content: str,
        extra: Optional[Dict[str, Any]] = None,
        client_msg_no: Optional[str] = None,
    ) -> Optional[WuKongIMMessageSendResponse]:
        """发送纯文本消息的便捷方法。
        
        自动封装文本消息格式、自动生成 UUID 作为 client_msg_no。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_text_message")
            return None

        # 标准文本消息 payload
        payload: Dict[str, Any] = {
            "type": MessageType.TEXT,
            "content": content,
        }
        if extra:
            payload["extra"] = extra

        return await self.send_message(
            payload=payload,
            from_uid=from_uid,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=client_msg_no or str(uuid4()),
        )
    async def send_staff_assigned_message(
        self,
        *,
        from_uid: str,
        channel_id: str,
        channel_type: int,
        staff_uid: str,
        staff_name: str,
        client_msg_no: Optional[str] = None,
    ) -> Optional[WuKongIMMessageSendResponse]:
        """发送「客服分配」系统通知消息。
        
        系统消息类型号 1000，访客接入客服时推送，告知已分配坐席。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_staff_assigned_message")
            return None

        payload: Dict[str, Any] = {
            "type": MessageType.STAFF_ASSIGNED,
            "content": "You have been connected to customer service. Agent {0} will assist you.",
            "extra": [
                {"uid": staff_uid, "name": staff_name},
            ],
        }

        logger.info(
            "Sending staff assigned system message",
            extra={
                "from_uid": from_uid,
                "channel_id": channel_id,
                "channel_type": channel_type,
                "staff_uid": staff_uid,
                "staff_name": staff_name,
            }
        )

        return await self.send_message(
            payload=payload,
            from_uid=from_uid,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=client_msg_no or str(uuid4()),
        )
    async def send_session_closed_message(
        self,
        *,
        from_uid: str,
        channel_id: str,
        channel_type: int,
        staff_uid: Optional[str] = None,
        staff_name: Optional[str] = None,
        client_msg_no: Optional[str] = None,
    ) -> Optional[WuKongIMMessageSendResponse]:
        """发送「会话结束」系统通知消息。
        
        系统消息类型号 1001，支持带坐席信息和纯结束两种文案。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_session_closed_message")
            return None

        # 有坐席信息：显示坐席结束服务文案
        if staff_uid and staff_name:
            payload: Dict[str, Any] = {
                "type": MessageType.SESSION_CLOSED,
                "content": "Session ended. Agent {0} has completed the service.",
                "extra": [
                    {"uid": staff_uid, "name": staff_name},
                ],
            }
        else:
            # 无坐席信息：通用结束文案
            payload = {
                "type": MessageType.SESSION_CLOSED,
                "content": "Session ended.",
                "extra": [],
            }

        logger.info(
            "Sending session closed system message",
            extra={
                "from_uid": from_uid,
                "channel_id": channel_id,
                "channel_type": channel_type,
                "staff_uid": staff_uid,
                "staff_name": staff_name,
            }
        )

        return await self.send_message(
            payload=payload,
            from_uid=from_uid,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=client_msg_no or str(uuid4()),
        )
    async def send_session_transferred_message(
        self,
        *,
        from_uid: str,
        channel_id: str,
        channel_type: int,
        from_staff_uid: str,
        from_staff_name: str,
        to_staff_uid: str,
        to_staff_name: str,
        client_msg_no: Optional[str] = None,
    ) -> Optional[WuKongIMMessageSendResponse]:
        """发送「会话转接」系统通知消息。
        
        系统消息类型号 1002，坐席转接时通知访客。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_session_transferred_message")
            return None

        payload: Dict[str, Any] = {
            "type": MessageType.SESSION_TRANSFERRED,
            "content": "Session transferred. Agent {0} has transferred you to Agent {1}.",
            "extra": [
                {"uid": from_staff_uid, "name": from_staff_name},
                {"uid": to_staff_uid, "name": to_staff_name},
            ],
        }

        logger.info(
            "Sending session transferred system message",
            extra={
                "from_uid": from_uid,
                "channel_id": channel_id,
                "channel_type": channel_type,
                "from_staff_uid": from_staff_uid,
                "from_staff_name": from_staff_name,
                "to_staff_uid": to_staff_uid,
                "to_staff_name": to_staff_name,
            }
        )

        return await self.send_message(
            payload=payload,
            from_uid=from_uid,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=client_msg_no or str(uuid4()),
        )
    async def send_system_message(
        self,
        *,
        channel_id: str,
        channel_type: int,
        content: str,
        msg_type: MessageType,
        from_uid: Optional[str] = None,
        extra: Optional[Any] = None,
        client_msg_no: Optional[str] = None,
    ) -> Optional[WuKongIMMessageSendResponse]:
        """通用系统消息发送方法，是上述几种系统通知的抽象父方法。"""
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_system_message")
            return None

        payload: Dict[str, Any] = {
            "type": msg_type,
            "content": content,
        }
        if extra:
            payload["extra"] = extra

        logger.info(
            "Sending system message",
            extra={
                "from_uid": from_uid,
                "channel_id": channel_id,
                "channel_type": channel_type,
                "msg_type": msg_type,
            }
        )

        return await self.send_message(
            payload=payload,
            from_uid=from_uid,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=client_msg_no or str(uuid4()),
        )
    async def send_visitor_profile_updated(
        self,
        *,
        visitor_id: str,
        channel_id: str,
        channel_type: int,
        client_msg_no: Optional[str] = None,
    ) -> Optional[WuKongIMMessageSendResponse]:
        """发送「访客资料更新」事件。
        
        访客标签、AI洞察、系统信息变化时触发，通知频道内所有订阅者刷新资料。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_visitor_profile_updated")
            return None

        event_type = EventType.VISITOR_PROFILE_UPDATED
        data = {
            "visitor_id": visitor_id,
            "channel_id": channel_id,
            "channel_type": channel_type,
        }

        logger.info(
            "Sending visitor profile updated event",
            extra={
                "visitor_id": visitor_id,
                "channel_id": channel_id,
                "channel_type": channel_type,
            }
        )

        return await self.send_event(
            client_msg_no=client_msg_no or f"profile-update-{uuid4().hex}",
            channel_id=channel_id,
            channel_type=channel_type,
            event_type=event_type,
            data=data,
            force=False,
        )
    async def send_queue_updated_event(
        self,
        *,
        channel_id: str,
        channel_type: int,
        project_id: str,
        waiting_count: int,
        client_msg_no: Optional[str] = None,
    ) -> Optional[WuKongIMMessageSendResponse]:
        """发送「排队队列更新」事件。
        
        新访客进入排队时，推送到项目坐席频道，通知所有坐席排队人数变化。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping send_queue_updated_event")
            return None

        event_type = EventType.QUEUE_UPDATED
        data = {
            "project_id": project_id,
            "waiting_count": waiting_count,
        }

        logger.info(
            "Sending queue updated event",
            extra={
                "channel_id": channel_id,
                "channel_type": channel_type,
                "project_id": project_id,
                "waiting_count": waiting_count,
            }
        )

        return await self.send_event(
            client_msg_no=client_msg_no or f"queue-update-{uuid4().hex}",
            channel_id=channel_id,
            channel_type=channel_type,
            event_type=event_type,
            data=data,
            force=True,
        )    

    async def get_channel_last_message(
        self,
        *,
        channel_id: str,
        channel_type: int,
        login_uid: Optional[str] = None,
    ) -> Optional[WuKongIMChannelLastMessage]:
        """获取指定频道的最后一条消息。
        
        Args:
            login_uid: 登录用户 UID，私聊频道（type=1）必须传
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping get_channel_last_message")
            return None

        params: Dict[str, Any] = {
            "channel_id": channel_id,
            "channel_type": channel_type,
        }
        if login_uid:
            params["login_uid"] = login_uid

        logger.debug(
            "Getting channel last message",
            extra={
                "channel_id": channel_id,
                "channel_type": channel_type,
            }
        )

        try:
            response = await self._make_request("GET", "/channel/last_message", params=params)
            
            if not response:
                return None
            
            # 自动解码 payload 字段
            if "payload" in response and isinstance(response["payload"], str):
                response["payload"] = self._decode_message_payload(response["payload"])
            
            return WuKongIMChannelLastMessage(**response)
        except Exception as e:
            # 404 等无消息场景返回 None，不抛异常
            logger.debug(f"Failed to get channel last message: {e}")
            return None
    async def get_channel_max_message_seq(
        self,
        *,
        channel_id: str,
        channel_type: int,
        login_uid: str,
    ) -> Optional[int]:
        """获取频道最大消息序号，用于增量同步消息的锚点。"""
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping get_channel_max_message_seq")
            return None

        params = {
            "channel_id": channel_id,
            "channel_type": channel_type,
            "login_uid": login_uid,
        }

        logger.debug(
            "Getting channel max message seq",
            extra={
                "channel_id": channel_id,
                "channel_type": channel_type,
                "login_uid": login_uid,
            }
        )

        try:
            response = await self._make_request("GET", "/channel/max_message_seq", params=params)
            if response and "message_seq" in response:
                return response["message_seq"]
            return None
        except Exception as e:
            logger.error(f"Failed to get channel max message seq: {e}")
            return None
    async def get_message_by_client_msg_no(
        self,
        *,
        channel_id: str,
        channel_type: int,
        client_msg_no: str,
    ) -> Optional[WuKongIMMessage]:
        """根据客户端消息号（client_msg_no）查询单条消息详情。"""
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping get_message_by_client_msg_no")
            return None

        if not client_msg_no:
            return None

        request_data = {
            "channel_id": channel_id,
            "channel_type": channel_type,
            "client_msg_no": client_msg_no
        }

        logger.info(
            "Getting message by client_msg_no",
            extra={
                "channel_id": channel_id,
                "channel_type": channel_type,
                "client_msg_no": client_msg_no
            }
        )

        try:
            response = await self._make_request(
                method="GET",
                endpoint="/message/byclientmsgno",
                params=request_data,
            )

            if not response:
                return None

            # 自动解码 payload
            if "payload" in response and isinstance(response["payload"], str):
                response["payload"] = self._decode_message_payload(response["payload"])

            return WuKongIMMessage(**response)
        except Exception as e:
            logger.error(f"Failed to get message by client_msg_no {client_msg_no}: {e}")
            return None
    async def create_channel(
        self,
        *,
        channel_id: str,
        channel_type: int,
        subscribers: List[str],
    ) -> Dict[str, Any]:
        """创建或更新频道，并设置订阅者列表。
        
        频道不存在则创建，已存在则更新订阅者。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping create_channel")
            return {}

        request_data: Dict[str, Any] = {
            "channel_id": channel_id,
            "channel_type": channel_type,
            "subscribers": subscribers or [],
        }

        logger.info(
            "Creating/updating WuKongIM channel",
            extra={
                "channel_id": channel_id,
                "channel_type": channel_type,
                "subscribers_count": len(subscribers or []),
            },
        )

        result = await self._make_request(
            method="POST",
            endpoint="/channel",
            json_data=request_data,
        )

        logger.debug("WuKongIM create_channel result: %s", result)
        return result
    async def add_channel_subscribers(
        self,
        *,
        channel_id: str,
        channel_type: int,
        subscribers: List[str],
        reset: bool = False,
    ) -> Dict[str, Any]:
        """向频道添加订阅者，幂等操作（重复添加安全）。
        
        Args:
            reset: True 时先清空原有订阅者再设置新列表，False 时追加
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping add_channel_subscribers")
            return {}

        if not subscribers:
            logger.debug("No subscribers provided; skipping add_channel_subscribers")
            return {}

        request_data: Dict[str, Any] = {
            "channel_id": channel_id,
            "channel_type": channel_type,
            "subscribers": subscribers,
            "reset": 1 if reset else 0,
        }

        logger.info(
            "Adding subscribers to WuKongIM channel",
            extra={
                "channel_id": channel_id,
                "channel_type": channel_type,
                "subscribers_count": len(subscribers),
                "reset": reset,
            },
        )

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/channel/subscriber_add",
                json_data=request_data,
            )

            logger.debug("WuKongIM add_channel_subscribers result: %s", result)
            return result
        except Exception as e:
            logger.error(
                f"Failed to add subscribers to channel {channel_id}: {e}",
                extra={
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "subscribers": subscribers,
                },
            )
            raise
    async def remove_channel_subscribers(
        self,
        *,
        channel_id: str,
        channel_type: int,
        subscribers: List[str],
    ) -> Dict[str, Any]:
        """从频道移除指定订阅者，幂等操作（移除不存在的用户安全）。"""
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping remove_channel_subscribers")
            return {}

        if not subscribers:
            logger.debug("No subscribers provided; skipping remove_channel_subscribers")
            return {}

        request_data: Dict[str, Any] = {
            "channel_id": channel_id,
            "channel_type": channel_type,
            "subscribers": subscribers,
        }

        logger.info(
            "Removing subscribers from WuKongIM channel",
            extra={
                "channel_id": channel_id,
                "channel_type": channel_type,
                "subscribers_count": len(subscribers),
            },
        )

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/channel/subscriber_remove",
                json_data=request_data,
            )

            logger.debug("WuKongIM remove_channel_subscribers result: %s", result)
            return result
        except Exception as e:
            logger.error(
                f"Failed to remove subscribers from channel {channel_id}: {e}",
                extra={
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                    "subscribers": subscribers,
                },
            )
            raise
    async def remove_all_channel_subscribers(
        self,
        *,
        channel_id: str,
        channel_type: int,
    ) -> Dict[str, Any]:
        """清空频道所有订阅者，同时会级联删除相关会话和标签。
        
        注意：私聊频道（type=1）不支持此操作。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled; skipping remove_all_channel_subscribers")
            return {}

        request_data: Dict[str, Any] = {
            "channel_id": channel_id,
            "channel_type": channel_type,
        }

        logger.info(
            "Removing all subscribers from WuKongIM channel",
            extra={
                "channel_id": channel_id,
                "channel_type": channel_type,
            },
        )

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/channel/subscriber_remove_all",
                json_data=request_data,
            )

            logger.info(
                f"Successfully removed all subscribers from channel {channel_id}",
                extra={
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                },
            )
            return result
        except Exception as e:
            logger.error(
                f"Failed to remove all subscribers from channel {channel_id}: {e}",
                extra={
                    "channel_id": channel_id,
                    "channel_type": channel_type,
                },
            )
            raise
    async def search_user_messages(
        self,
        *,
        uid: str,
        keyword: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
        payload_types: Optional[List[int]] = None,
        from_uid: Optional[str] = None,
        channel_id: Optional[str] = None,
        channel_type: Optional[int] = None,
        topic: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        highlights: Optional[List[str]] = None,
    ) -> WuKongIMSearchMessagesResponse:
        """调用 WuKongIM 搜索插件，按条件搜索用户历史消息。
        
        支持关键词、发送者、频道、时间范围、消息类型等多维度筛选，
        结果自动解码 payload，返回结构化搜索结果。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration disabled; skipping message search")
            return WuKongIMSearchMessagesResponse(messages=[], total=0)

        # 基础参数 + 边界校验
        request_data: Dict[str, Any] = {
            "uid": uid,
            "limit": max(1, min(limit, 100)),  # 每页 1-100 条限制
            "page": max(page, 1),
        }

        # payload 内容筛选
        payload_filter: Dict[str, Any] = {}
        if keyword:
            payload_filter["content"] = keyword
        if payload_filter:
            request_data["payload"] = payload_filter

        # 其他筛选条件按需添加
        if payload_types:
            request_data["payload_types"] = payload_types
        if from_uid:
            request_data["from_uid"] = from_uid
        if channel_id:
            request_data["channel_id"] = channel_id
        if channel_type is not None:
            request_data["channel_type"] = channel_type
        if topic:
            request_data["topic"] = topic
        if start_time:
            request_data["start_time"] = start_time
        if end_time:
            request_data["end_time"] = end_time

        # 高亮字段：传了就用，没传但有关键词就默认高亮内容
        if highlights is not None:
            request_data["highlights"] = highlights
        elif keyword:
            request_data["highlights"] = ["payload.content"]

        response = await self._make_request(
            method="POST",
            endpoint="/plugins/wk.plugin.search/usersearch",
            json_data=request_data,
        )

        raw_messages = response.get("messages") or []
        processed_messages: List[WuKongIMSearchResult] = []
        for raw in raw_messages:
            item = dict(raw) if isinstance(raw, dict) else {}
            payload_raw = item.get("payload")
            # 逐条解码 payload
            if isinstance(payload_raw, str):
                item["payload"] = self._decode_message_payload(payload_raw)

            processed_messages.append(WuKongIMSearchResult(**item))

        total = response.get("total", len(processed_messages))
        return WuKongIMSearchMessagesResponse(messages=processed_messages, total=total)
    async def register_or_login_user(
        self,
        uid: str,
        token: Optional[str] = None,
        device_flag: Optional[int] = None,
        device_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """用户注册/登录 WuKongIM，生成并绑定连接 token。
        
        用户连接 IM WebSocket 前必须先调用此接口获取鉴权 token。

        Args:
            uid: 用户唯一标识
            token: 自定义 token，不传则自动生成 UUID
            device_flag: 设备类型（0=APP 1=Web 2=PC）
            device_level: 设备级别（0=副设备 1=主设备）
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return {}

        # 参数默认值：未传则用配置或自动生成
        token = token or str(uuid4())
        device_flag = device_flag if device_flag is not None else settings.WUKONGIM_DEVICE_FLAG
        device_level = device_level if device_level is not None else settings.WUKONGIM_DEVICE_LEVEL

        request_data = {
            "uid": uid,
            "token": token,
            "device_flag": device_flag,
            "device_level": device_level,
        }

        logger.info(
            f"Registering user with WuKongIM",
            extra={
                "uid": uid,
                "device_flag": device_flag,
                "device_level": device_level,
            }
        )

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/user/token",
                json_data=request_data,
            )

            logger.info(f"Successfully registered user {uid} with WuKongIM")
            return result

        except Exception as e:
            logger.error(
                f"Failed to register user {uid} with WuKongIM: {e}",
                extra={"uid": uid, "error": str(e)}
            )
            raise
    async def check_user_online_status(self, uids: list[str]) -> list[str]:
        """批量查询用户在线状态，返回在线用户 UID 列表。
        
        出错时返回空列表，降级处理，不影响主业务流程。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return []

        if not uids:
            return []

        logger.debug(f"Checking online status for {len(uids)} users")

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/user/onlinestatus",
                json_data=uids,
            )

            # 解析响应，筛选出 online=1 的用户
            online_items = [WuKongIMOnlineStatusItem(**item) for item in result] if isinstance(result, list) else []
            online_uids = [item.uid for item in online_items if item.online == 1]
            
            logger.debug(f"Found {len(online_uids)} online users out of {len(uids)} checked")
            return online_uids

        except Exception as e:
            logger.error(f"Failed to check user online status: {e}")
            # 降级：出错返回空列表，避免中断主流程
            return []
    async def add_system_accounts(self, uids: list[str]) -> Dict[str, Any]:
        """添加系统账号，系统账号拥有完整消息收发权限，不受普通权限限制。
        
        一般用于客服系统账号、机器人账号等。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return {}

        if not uids:
            return {}

        request_data = {"uids": uids}

        logger.info(f"Adding {len(uids)} system accounts to WuKongIM")

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/user/systemuids_add",
                json_data=request_data,
            )

            logger.info(f"Successfully added {len(uids)} system accounts")
            return result

        except Exception as e:
            logger.error(f"Failed to add system accounts: {e}")
            raise
    async def remove_system_accounts(self, uids: list[str]) -> Dict[str, Any]:
        """移除系统账号权限。"""
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return {}

        if not uids:
            return {}

        request_data = {"uids": uids}

        logger.info(f"Removing {len(uids)} system accounts from WuKongIM")

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/user/systemuids_remove",
                json_data=request_data,
            )

            logger.info(f"Successfully removed {len(uids)} system accounts")
            return result

        except Exception as e:
            logger.error(f"Failed to remove system accounts: {e}")
            raise

    async def kick_user_device(
        self,
        uid: str,
        device_flag: int = -1,
    ) -> Dict[str, Any]:
        """踢用户设备下线，支持指定设备类型或全部踢下线。
        
        Args:
            device_flag: -1=全部设备 0=APP 1=Web 2=PC
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return {}

        request_data = {
            "uid": uid,
            "device_flag": device_flag,
        }

        logger.info(f"Kicking user {uid} device {device_flag} from WuKongIM")

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/user/device_quit",
                json_data=request_data,
            )

            logger.info(f"Successfully kicked user {uid} device {device_flag}")
            return result

        except Exception as e:
            logger.error(f"Failed to kick user device: {e}")
            raise
    async def sync_conversations(
        self,
        uid: str,
        version: int = 0,
        last_msg_seqs: Optional[str] = None,
        msg_count: int = 20,
    ) -> List[WuKongIMConversation]:
        """同步用户的会话列表，支持增量同步。
        
        Args:
            version: 客户端本地会话最大版本号，0 表示全量同步
            last_msg_seqs: 各频道最后消息序号，用于增量同步
            msg_count: 每个会话附带的最近消息条数
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return []

        request_data = {
            "uid": uid,
            "version": version,
            "msg_count": msg_count,
            "stream_v2": 1,               # 启用流式 V2 协议
            "include_event_meta": 1,      # 包含事件元数据
            "event_summary_mode": "full", # 事件摘要完整模式
        }

        if last_msg_seqs:
            request_data["last_msg_seqs"] = last_msg_seqs

        logger.info(
            f"Syncing conversations for user {uid}",
            extra={
                "uid": uid,
                "version": version,
                "msg_count": msg_count,
                "has_last_msg_seqs": bool(last_msg_seqs),
            }
        )

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/conversation/sync",
                json_data=request_data,
            )

            conversations = result if isinstance(result, list) else []

            # 遍历所有会话的最近消息，自动解码 base64 payload
            for conversation in conversations:
                if "recents" in conversation and isinstance(conversation["recents"], list):
                    for message in conversation["recents"]:
                        if "payload" in message and isinstance(message["payload"], str):
                            message["payload"] = self._decode_message_payload(message["payload"])

                        # 兼容处理：移除旧字段 stream_data，统一用 event_meta
                        message.pop("stream_data", None)

            logger.info(f"Successfully synced {len(conversations)} conversations for user {uid}")
            return [WuKongIMConversation(**conv) for conv in conversations]

        except Exception as e:
            logger.error(f"Failed to sync conversations for user {uid}: {e}")
            raise
    async def sync_conversations_by_channels(
        self,
        uid: str,
        channels: List[Dict[str, Any]],
        msg_count: int = 20,
    ) -> List[WuKongIMConversation]:
        """按指定的频道列表，批量同步对应会话信息。"""
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return []

        if not channels:
            logger.debug("No channels provided for sync")
            return []

        request_data = {
            "uid": uid,
            "channels": channels,
            "msg_count": msg_count,
            "stream_v2": 1,
            "include_event_meta": 1,
            "event_summary_mode": "full",
        }

        logger.info(
            f"Syncing conversations by channels for user {uid}",
            extra={
                "uid": uid,
                "channel_count": len(channels),
                "msg_count": msg_count,
            }
        )

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/conversation/syncByChannels",
                json_data=request_data,
            )

            conversations = result if isinstance(result, list) else []

            # 同样自动解码 payload + 清理旧字段
            for conversation in conversations:
                if "recents" in conversation and isinstance(conversation["recents"], list):
                    for message in conversation["recents"]:
                        if "payload" in message and isinstance(message["payload"], str):
                            message["payload"] = self._decode_message_payload(message["payload"])

                        message.pop("stream_data", None)

            logger.info(f"Successfully synced {len(conversations)} conversations by channels for user {uid}")
            return [WuKongIMConversation(**conv) for conv in conversations]

        except Exception as e:
            logger.error(f"Failed to sync conversations by channels for user {uid}: {e}")
            raise
    async def set_conversation_unread(
        self,
        uid: str,
        channel_id: str,
        channel_type: int,
        unread: int,
    ) -> Dict[str, Any]:
        """设置指定会话的未读数。"""
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return {}

        request_data = {
            "uid": uid,
            "channel_id": channel_id,
            "channel_type": channel_type,
            "unread": unread,
        }

        logger.info(
            f"Setting unread count for user {uid}, channel {channel_id}",
            extra={
                "uid": uid,
                "channel_id": channel_id,
                "channel_type": channel_type,
                "unread": unread,
            }
        )

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/conversations/setUnread",
                json_data=request_data,
            )

            logger.info(f"Successfully set unread count for user {uid}, channel {channel_id}")
            return result

        except Exception as e:
            logger.error(f"Failed to set unread count for user {uid}, channel {channel_id}: {e}")
            raise
    async def delete_conversation(
        self,
        uid: str,
        channel_id: str,
        channel_type: int,
    ) -> Dict[str, Any]:
        """删除用户的指定会话。"""
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return {}

        request_data = {
            "uid": uid,
            "channel_id": channel_id,
            "channel_type": channel_type,
        }

        logger.info(
            f"Deleting conversation for user {uid}, channel {channel_id}",
            extra={
                "uid": uid,
                "channel_id": channel_id,
                "channel_type": channel_type,
            }
        )

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/conversations/delete",
                json_data=request_data,
            )

            logger.info(f"Successfully deleted conversation for user {uid}, channel {channel_id}")
            return result

        except Exception as e:
            logger.error(f"Failed to delete conversation for user {uid}, channel {channel_id}: {e}")
            raise
    async def sync_channel_messages(
        self,
        login_uid: str,
        channel_id: str,
        channel_type: int,
        start_message_seq: int = 0,
        end_message_seq: int = 0,
        limit: int = 100,
        pull_mode: int = 1,
        include_event_meta: int = 0,
        event_summary_mode: str = "basic",
    ) -> WuKongIMChannelMessageSyncResponse:
        """同步指定频道的历史消息，支持上下拉分页。
        
        Args:
            start_message_seq: 起始消息序号（包含）
            end_message_seq: 结束消息序号（不包含）
            pull_mode: 拉取方向（0=向下拉旧消息 1=向上拉新消息）
            include_event_meta: 是否包含流式事件元数据
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            return WuKongIMChannelMessageSyncResponse(
                start_message_seq=start_message_seq,
                end_message_seq=end_message_seq,
                more=0,
                messages=[]
            )

        request_data = {
            "login_uid": login_uid,
            "channel_id": channel_id,
            "channel_type": channel_type,
            "start_message_seq": start_message_seq,
            "end_message_seq": end_message_seq,
            "limit": limit,
            "pull_mode": pull_mode,
            "stream_v2": 1,
        }
        if include_event_meta:
            request_data["include_event_meta"] = include_event_meta
            request_data["event_summary_mode"] = event_summary_mode

        logger.info(
            f"Syncing channel messages for user {login_uid}",
            extra={
                "login_uid": login_uid,
                "channel_id": channel_id,
                "channel_type": channel_type,
                "start_message_seq": start_message_seq,
                "end_message_seq": end_message_seq,
                "limit": limit,
                "pull_mode": pull_mode,
                "stream_v2": 1,
            }
        )

        try:
            result = await self._make_request(
                method="POST",
                endpoint="/channel/messagesync",
                json_data=request_data,
            )

            # 批量解码消息 payload
            if "messages" in result and isinstance(result["messages"], list):
                for message in result["messages"]:
                    if "payload" in message and isinstance(message["payload"], str):
                        message["payload"] = self._decode_message_payload(message["payload"])

                    # 移除旧版流数据字段，统一用 event_meta
                    message.pop("stream_data", None)

            message_count = len(result.get("messages", []))
            logger.info(f"Successfully synced {message_count} channel messages for user {login_uid}")
            return WuKongIMChannelMessageSyncResponse(**result)

        except Exception as e:
            logger.error(f"Failed to sync channel messages for user {login_uid}: {e}")
            raise

    async def get_route(self, uid: str) -> WuKongIMRouteResponse:
        """获取用户的 WebSocket 连接地址（TCP + WS）。
        
        客户端连接 IM 前调用此接口，获取最优接入节点地址。
        服务禁用时直接抛出 503 异常（此接口是连接前置，禁用则无法使用）。
        """
        if not self.enabled:
            logger.debug("WuKongIM integration is disabled")
            raise HTTPException(
                status_code=503,
                detail="WuKongIM service is disabled"
            )

        logger.info(f"Getting route for user {uid}")

        try:
            result = await self._make_request(
                method="GET",
                endpoint="/route",
                params={"uid": uid},
            )

            logger.info(f"Successfully retrieved route for user {uid}")
            return WuKongIMRouteResponse(**result)

        except Exception as e:
            logger.error(f"Failed to get route for user {uid}: {e}")
            raise
# 全局 WuKongIM 客户端单例，业务层直接导入此实例使用，避免重复初始化
wukongim_client = WuKongIMClient()