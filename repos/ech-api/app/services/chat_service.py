# =============================================================================
# 模块：聊天服务 (Chat service)
# =============================================================================
# 该模块提供了聊天完成业务逻辑的核心服务，主要包括：
# 1. AI 流式/非流式响应处理
# 2. 与 WuKongIM 的消息转发和事件推送
# 3. 访客验证、创建和状态管理
# 4. OpenAI 兼容格式的请求/响应处理
# 5. 平台和项目验证
# 6. 访客与队列管理
# 
# 这是整个聊天系统的中枢模块，连接了 AI 服务、IM 服务和业务逻辑。
# =============================================================================

import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import (
    Platform,
    Project,
    Visitor,
    VisitorServiceStatus,
    VisitorWaitingQueue,
    VisitorAssignmentRule,
    QueueSource,
    WaitingStatus,
    Staff,
)
import app.services.visitor_service as visitor_service
from app.tasks.process_waiting_queue import trigger_process_entry
from app.services.wukongim_client import wukongim_client
from app.services.ai_client import AIServiceClient
from app.utils.encoding import build_project_staff_channel_id
from app.utils.const import (
    CHANNEL_TYPE_PROJECT_STAFF,
    CHANNEL_TYPE_CUSTOMER_SERVICE,
    MessageType,
)
from app.schemas.chat import (
    OpenAIChatMessage,
    OpenAIChatCompletionResponse,
    OpenAIChatCompletionChoice,
    OpenAIChatCompletionUsage,
)

logger = get_logger("services.chat")

# 全局 AI 客户端实例
ai_client = AIServiceClient()


# =============================================================================
# 第一部分：验证与辅助函数
# =============================================================================

def validate_platform_and_project(
    platform_api_key: str,
    db: Session
) -> tuple[Platform, Project]:
    """
    验证平台 API Key 并返回平台和关联的项目。

    执行流程：
    1. 根据 API Key 查询平台
    2. 验证平台是否激活且未删除
    3. 验证平台是否关联了有效的项目

    Args:
        platform_api_key: 平台的 API Key
        db: 数据库会话

    Returns:
        tuple[Platform, Project]: (平台对象, 项目对象)

    Raises:
        HTTPException: API Key 无效或项目无效时抛出 401/400 错误
    """
    # 查询平台
    platform = (
        db.query(Platform)
        .filter(
            Platform.api_key == platform_api_key,
            Platform.is_active.is_(True),
            Platform.deleted_at.is_(None),
        )
        .first()
    )
    if not platform:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    # 验证关联的项目
    project = platform.project
    if not project or not project.api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Platform is not linked to a valid project"
        )

    return platform, project


def is_ai_disabled(platform: Platform, visitor: Optional[Visitor]) -> bool:
    """
    检查平台或访客是否禁用了 AI。

    优先级逻辑：
    1. 如果访客的 ai_disabled 已显式设置（不为 None），使用该值
    2. 否则，检查平台的 ai_mode：
       - "auto" 表示 AI 启用（返回 False）
       - 其他值表示 AI 禁用（返回 True）

    设计考量：
    - 访客级别配置覆盖平台级别配置
    - 支持动态调整单个访客的 AI 状态

    Args:
        platform: 平台对象
        visitor: 访客对象（可选）

    Returns:
        bool: True 表示 AI 被禁用，False 表示 AI 启用
    """
    # 优先使用访客的 ai_disabled 设置
    if visitor is not None:
        visitor_ai_disabled = getattr(visitor, "ai_disabled", None)
        if visitor_ai_disabled is not None:
            return visitor_ai_disabled

    # 回退到平台的 ai_mode 配置
    ai_mode = getattr(platform, "ai_mode", None)
    return ai_mode != "auto"


def sse_format(event: Dict[str, Any]) -> str:
    """
    将事件格式化为 Server-Sent Events (SSE) 消息格式。

    SSE 格式规范：
    - 事件类型行: event: <type>
    - 数据行: data: <json>
    - 空行分隔: \n\n

    Args:
        event: 事件字典，包含 event_type 和 data

    Returns:
        str: 格式化后的 SSE 消息字符串
    """
    event_type = event.get("event_type") or "message"
    data = json.dumps(event, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"


def authenticate_staff_or_platform(
    db: Session,
    credentials: Optional[HTTPAuthorizationCredentials] = None,
    platform_api_key: Optional[str] = None,
) -> tuple[Optional[Staff], Optional[Platform]]:
    """
    通过 JWT（客服认证）或平台 API Key 进行认证。

    认证优先级：
    1. 首先尝试 JWT 认证（客服身份）
    2. 如果 JWT 认证失败，尝试平台 API Key 认证

    使用场景：
    - 客服端访问 API：使用 JWT
    - 平台端访问 API：使用 API Key

    Args:
        db: 数据库会话
        credentials: HTTP 认证凭证（包含 JWT）
        platform_api_key: 平台 API Key

    Returns:
        tuple[Optional[Staff], Optional[Platform]]: (客服对象, 平台对象)
    """
    current_user: Optional[Staff] = None
    platform: Optional[Platform] = None

    # 1. 尝试 JWT 认证（客服）
    if credentials and credentials.credentials:
        from app.core.security import verify_token
        payload = verify_token(credentials.credentials)
        if payload:
            username = payload.get("sub")
            if username:
                current_user = (
                    db.query(Staff)
                    .filter(Staff.username == username, Staff.deleted_at.is_(None))
                    .first()
                )

    # 2. 如果客服认证失败，尝试平台 API Key 认证
    if not current_user and platform_api_key:
        platform = (
            db.query(Platform)
            .filter(
                Platform.api_key == platform_api_key,
                Platform.is_active.is_(True),
                Platform.deleted_at.is_(None),
            )
            .first()
        )

    return current_user, platform


# =============================================================================
# 第二部分：AI 集成逻辑
# =============================================================================

async def forward_ai_event_to_wukongim(
    event_type: str,
    event_data: Dict[str, Any],
    channel_id: str,
    channel_type: int,
    client_msg_no: str,
    from_uid: str,
) -> Optional[str]:
    """
    将 AI 事件转发到 WuKongIM（使用流式 API）。

    事件类型映射：
    - agent_execution_started → 发送流式锚点消息（is_stream=1）
    - agent_content_chunk → 发送流式增量事件（stream.delta）
    - workflow_completed / agent_response_complete → 关闭流并完成
    - workflow_failed → 发送错误事件（stream.error）

    设计考量：
    - AI 生成的流式内容实时推送到 IM，用户可即时看到回复
    - 使用 WuKongIM 的流式消息能力，支持增量更新
    - 错误事件也会推送到 IM，让用户了解处理状态

    Args:
        event_type: AI 事件类型
        event_data: AI 事件数据
        channel_id: 频道 ID
        channel_type: 频道类型
        client_msg_no: 客户端消息编号
        from_uid: 发送者 UID

    Returns:
        Optional[str]: 如果是内容块事件，返回内容片段；否则返回 None
    """
    try:
        data = event_data.get("data") or {}
        logger.info(f"Forwarding AI event {event_type} to WuKongIM: {data}")

        # =====================================================================
        # 事件1: Agent 执行开始
        # =====================================================================
        if event_type == "agent_execution_started":
            # 发送流式锚点消息，告知用户 AI 正在处理
            await wukongim_client.send_stream_message(
                from_uid=from_uid,
                channel_id=channel_id,
                channel_type=channel_type,
                client_msg_no=client_msg_no,
                payload={"type": 100, "content": "AI 正在思考中..."},
            )

        # =====================================================================
        # 事件2: AI 内容块（增量输出）
        # =====================================================================
        elif event_type == "agent_content_chunk":
            # 健壮地提取内容：支持多种数据格式
            chunk_text = (
                data.get("content_chunk") or
                data.get("content") or
                data.get("text")
            )
            if not chunk_text and isinstance(data, dict):
                inner_data = data.get("data", {})
                if isinstance(inner_data, dict):
                    chunk_text = (
                        inner_data.get("content_chunk") or
                        inner_data.get("content") or
                        inner_data.get("text")
                    )

            if chunk_text is not None:
                chunk_str = str(chunk_text)
                if not chunk_str:
                    return None
                # 发送流式增量事件
                await wukongim_client.send_stream_event(
                    channel_id=channel_id,
                    channel_type=channel_type,
                    client_msg_no=client_msg_no,
                    event_id=uuid4().hex,
                    event_type="stream.delta",
                    event_key="main",
                    from_uid=from_uid,
                    payload={"kind": "text", "delta": chunk_str},
                )
                return chunk_str

        # =====================================================================
        # 事件3: 工作流完成 / Agent 响应完成
        # =====================================================================
        elif event_type in {"workflow_completed", "agent_response_complete"}:
            # 先关闭流通道
            await wukongim_client.send_stream_event(
                channel_id=channel_id,
                channel_type=channel_type,
                client_msg_no=client_msg_no,
                event_id=uuid4().hex,
                event_type="stream.close",
                event_key="main",
                from_uid=from_uid,
            )
            # 再发送完成事件
            await wukongim_client.send_stream_event(
                channel_id=channel_id,
                channel_type=channel_type,
                client_msg_no=client_msg_no,
                event_id=uuid4().hex,
                event_type="stream.finish",
                event_key="main",
                from_uid=from_uid,
            )

        # =====================================================================
        # 事件4: 工作流失败
        # =====================================================================
        elif event_type == "workflow_failed":
            error_message = data.get("error") or "AI processing failed"
            await wukongim_client.send_stream_event(
                channel_id=channel_id,
                channel_type=channel_type,
                client_msg_no=client_msg_no,
                event_id=uuid4().hex,
                event_type="stream.error",
                event_key="main",
                from_uid=from_uid,
                payload={"error": str(error_message)},
            )

    except Exception as e:
        logger.error(f"Failed to forward AI event {event_type} to WuKongIM: {e}")
    return None


async def process_ai_stream_to_wukongim(
    project_id: str,
    user_id: str,
    message: str,
    channel_id: str,
    channel_type: int,
    client_msg_no: str,
    from_uid: str,
    session_id: Optional[str] = None,
    system_message: Optional[str] = None,
    expected_output: Optional[str] = None,
    agent_id: Optional[str] = None,
):
    """
    处理 AI 流式响应并将事件转发到 WuKongIM，同时为 SSE 产生事件。

    这是一个生成器函数，同时做两件事：
    1. 将 AI 的流式输出转发到 WuKongIM（实时展示给用户）
    2. 将事件 yield 给调用方（用于 SSE 响应）

    执行流程：
    1. 调用 AI 客户端的流式方法
    2. 对每个收到的 AI 事件，转发到 WuKongIM
    3. 同时 yield 事件给调用方

    Args:
        project_id: 项目 ID
        user_id: 用户 ID（访客 ID）
        message: 用户消息
        channel_id: 频道 ID
        channel_type: 频道类型
        client_msg_no: 客户端消息编号
        from_uid: 发送者 UID
        session_id: 会话 ID（可选）
        system_message: 系统提示词（可选）
        expected_output: 期望输出格式（可选）
        agent_id: Agent ID（可选）

    Yields:
        Dict[str, Any]: SSE 事件，包含 event_type 和 data
    """
    full_content = ""

    # =====================================================================
    # 调用 AI 流式处理
    # =====================================================================
    try:
        async for stream_event_type, data in ai_client.run_supervisor_agent_stream(
            project_id=project_id,
            agent_id=agent_id,
            user_id=user_id,
            message=message,
            session_id=session_id,
            enable_memory=True,
            system_message=system_message,
            expected_output=expected_output,
        ):
            # 提取事件类型
            event_type = data.get("event_type") if isinstance(data, dict) else None
            if not event_type:
                event_type = stream_event_type

            # 转发到 WuKongIM
            content_chunk = await forward_ai_event_to_wukongim(
                event_type=event_type,
                event_data=data,
                channel_id=channel_id,
                channel_type=channel_type,
                client_msg_no=client_msg_no,
                from_uid=from_uid,
            )
            if content_chunk:
                full_content += content_chunk

            # 为 SSE 产生事件
            yield {"event_type": event_type, "data": data}

    except Exception as e:
        logger.error(f"Error in AI stream processing: {e}")
        # 发送错误事件
        error_data = {"error_message": str(e)}
        await forward_ai_event_to_wukongim(
            event_type="workflow_failed",
            event_data=error_data,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=client_msg_no,
            from_uid=from_uid,
        )
        yield {"event_type": "workflow_failed", "data": error_data}


async def handle_ai_response_non_stream(
    project_id: str,
    visitor_id: str,
    message: str,
    channel_id: str,
    channel_type: int,
    client_msg_no: str,
    from_uid: str,
    session_id: Optional[str] = None,
    system_message: Optional[str] = None,
    expected_output: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    以非流式方式处理 AI 响应，同时仍将内容转发到 WuKongIM。

    与流式处理的区别：
    - 等待完整的 AI 响应完成后返回
    - 适合需要完整结果的场景（如自动兜底）
    - 在等待过程中，内容仍会流式推送到 IM

    Args:
        project_id: 项目 ID
        visitor_id: 访客 ID
        message: 用户消息
        channel_id: 频道 ID
        channel_type: 频道类型
        client_msg_no: 客户端消息编号
        from_uid: 发送者 UID
        session_id: 会话 ID（可选）
        system_message: 系统提示词（可选）
        expected_output: 期望输出格式（可选）
        agent_id: Agent ID（可选）

    Returns:
        Dict[str, Any]: 包含 success, content, data 的响应字典
    """
    full_content = ""
    last_data = {}

    try:
        # 使用流式 API 但等待完整结果
        async for stream_event_type, data in ai_client.run_supervisor_agent_stream(
            project_id=project_id,
            agent_id=agent_id,
            user_id=visitor_id,
            message=message,
            session_id=session_id,
            enable_memory=True,
            system_message=system_message,
            expected_output=expected_output,
        ):
            event_type = data.get("event_type") if isinstance(data, dict) else None
            if not event_type:
                event_type = stream_event_type

            # 转发到 WuKongIM
            content_chunk = await forward_ai_event_to_wukongim(
                event_type=event_type,
                event_data=data,
                channel_id=channel_id,
                channel_type=channel_type,
                client_msg_no=client_msg_no,
                from_uid=from_uid,
            )
            if content_chunk:
                full_content += content_chunk
            last_data = data

        return {"success": True, "content": full_content, "data": last_data}

    except Exception as e:
        logger.error(f"Error in non-stream AI processing: {e}")
        error_data = {"error_message": str(e)}
        await forward_ai_event_to_wukongim(
            event_type="workflow_failed",
            event_data=error_data,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=client_msg_no,
            from_uid=from_uid,
        )
        return {"success": False, "error": str(e)}


async def run_background_ai_interaction(
    project_id: str,
    user_id: str,
    message: str,
    channel_id: str,
    channel_type: int,
    client_msg_no: str,
    from_uid: str,
    session_id: Optional[str] = None,
    system_message: Optional[str] = None,
    expected_output: Optional[str] = None,
    agent_id: Optional[str] = None,
    started_event: Optional[asyncio.Event] = None,
):
    """
    在后台运行 AI 交互。

    使用场景：
    - 异步处理 AI 响应，不阻塞主请求
    - 适合需要快速返回"已接收"状态的场景

    Args:
        started_event: 可选的 asyncio.Event，当 Agent 执行开始时会被设置
    """
    async for event_payload in process_ai_stream_to_wukongim(
        project_id=project_id,
        user_id=user_id,
        message=message,
        channel_id=channel_id,
        channel_type=channel_type,
        client_msg_no=client_msg_no,
        from_uid=from_uid,
        session_id=session_id,
        system_message=system_message,
        expected_output=expected_output,
        agent_id=agent_id,
    ):
        # 当 AI 处理开始时设置事件（用于通知调用方）
        if started_event and not started_event.is_set():
            event_type = event_payload.get("event_type")
            if event_type == "agent_execution_started":
                started_event.set()


# =============================================================================
# 第三部分：UI 用户操作处理
# =============================================================================

def convert_ui_user_action_to_query(user_action: Dict[str, Any]) -> str:
    """
    将 UI 用户操作载荷转换为自然语言查询。

    前端在用户与交互式 UI 组件交互时发送：
    ``{ "actionName": "...", "context": {...} }``

    我们将其转换为人类可读的消息，以便 LLM Agent 能够自然响应。

    示例：
    输入: {"actionName": "search_restaurant", "context": {"cuisine": "Chinese", "location": "NYC"}}
    输出: "[UI Action] User triggered action 'search_restaurant' with context: cuisine=Chinese, location=NYC"

    Args:
        user_action: 用户操作字典

    Returns:
        str: 自然语言查询字符串
    """
    action_name = user_action.get("actionName", "unknown_action")
    context = user_action.get("context", {})

    # 构建上下文描述
    context_parts = [f"{k}={v}" for k, v in context.items() if v]
    context_str = ", ".join(context_parts) if context_parts else "no additional context"

    return f"[UI Action] User triggered action '{action_name}' with context: {context_str}"


# =============================================================================
# 第四部分：OpenAI 格式映射辅助函数
# =============================================================================

def extract_messages_from_openai_format(
    messages: list[OpenAIChatMessage],
    user_field: Optional[str] = None
) -> tuple[str, Optional[str], str]:
    """
    从 OpenAI 消息格式中提取用户消息、系统消息和平台用户 ID。

    处理逻辑：
    - 从消息列表中提取最后一条 user 消息作为用户消息
    - 提取 system 消息作为系统提示词（可选）
    - 生成或使用提供的 platform_open_id

    Args:
        messages: OpenAI 格式的消息列表
        user_field: 平台用户 ID（可选）

    Returns:
        tuple[str, Optional[str], str]: (用户消息, 系统消息, 平台用户ID)

    Raises:
        HTTPException: 如果没有用户消息
    """
    user_message = None
    system_message = None

    # 从后往前遍历消息，提取 user 和 system 消息
    for msg in reversed(messages):
        if msg.role == "user" and user_message is None:
            user_message = msg.content
        elif msg.role == "system" and system_message is None:
            system_message = msg.content

    if not user_message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user message found in messages array"
        )

    platform_open_id = user_field or f"openai_user_{uuid4().hex[:8]}"

    return user_message, system_message, platform_open_id


def estimate_token_usage(
    messages: list[OpenAIChatMessage],
    completion_text: str
) -> tuple[int, int, int]:
    """
    估算提示词和完成内容的 Token 使用量。

    这是一个简化的估算方法，使用分词数量作为近似值。
    实际生产中可考虑使用 tiktoken 等更精确的 Tokenizer。

    Args:
        messages: 消息列表
        completion_text: 完成内容

    Returns:
        tuple[int, int, int]: (提示词 Token 数, 完成 Token 数, 总 Token 数)
    """
    prompt_text = " ".join([msg.content for msg in messages])
    prompt_tokens = len(prompt_text.split())
    completion_tokens = len(completion_text.split())
    total_tokens = prompt_tokens + completion_tokens

    return prompt_tokens, completion_tokens, total_tokens


def build_openai_completion_response(
    completion_id: str,
    created_timestamp: int,
    model: str,
    completion_text: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int
) -> OpenAIChatCompletionResponse:
    """
    构建 OpenAI 兼容的完成响应。

    用于 OpenAI API 兼容模式的响应格式。

    Args:
        completion_id: 完成 ID
        created_timestamp: 创建时间戳
        model: 模型名称
        completion_text: 完成内容
        prompt_tokens: 提示词 Token 数
        completion_tokens: 完成 Token 数
        total_tokens: 总 Token 数

    Returns:
        OpenAIChatCompletionResponse: OpenAI 兼容的响应对象
    """
    return OpenAIChatCompletionResponse(
        id=completion_id,
        object="chat.completion",
        created=created_timestamp,
        model=model,
        choices=[
            OpenAIChatCompletionChoice(
                index=0,
                message=OpenAIChatMessage(
                    role="assistant",
                    content=completion_text,
                ),
                finish_reason="stop",
            )
        ],
        usage=OpenAIChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )


# =============================================================================
# 第五部分：消息发送辅助函数
# =============================================================================

async def send_user_message_to_wukongim(
    *,
    from_uid: str,
    channel_id: str,
    channel_type: int,
    content: str,
    msg_type: Optional[MessageType] = MessageType.TEXT,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    将用户消息的副本发送到 WuKongIM（尽力而为）。

    使用场景：
    - 将用户消息同步到 IM 系统
    - 支持文本、图片、文件等多种消息类型

    设计考量：
    - 尽力而为：发送失败不影响主流程
    - 支持消息类型扩展

    Args:
        from_uid: 发送者 UID
        channel_id: 频道 ID
        channel_type: 频道类型
        content: 消息内容
        msg_type: 消息类型（文本/图片/文件）
        extra: 额外参数（如文件名）
    """
    if not content:
        return

    try:
        # 根据消息类型构建载荷
        # 1=TEXT, 2=IMAGE, 3=FILE
        payload: Dict[str, Any] = {
            "type": int(msg_type or MessageType.TEXT),
            "content": content,
        }

        if msg_type == MessageType.IMAGE:
            payload["url"] = content
        elif msg_type == MessageType.FILE:
            payload["url"] = content
            # 文件通常需要名称（前端要求）
            if extra and extra.get("file_name"):
                payload["name"] = extra["file_name"]
            else:
                payload["name"] = content.split("/")[-1]

        if extra:
            payload["extra"] = extra

        await wukongim_client.send_message(
            payload=payload,
            from_uid=from_uid,
            channel_id=channel_id,
            channel_type=channel_type,
            client_msg_no=f"user_{uuid4().hex}",
        )
    except Exception:
        # 发送失败不抛出异常
        pass


# =============================================================================
# 第六部分：访客与队列管理
# =============================================================================

async def get_or_create_visitor(
    db: Session,
    platform: Platform,
    platform_open_id: str,
    nickname: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> tuple[Visitor, bool]:
    """
    获取或创建访客。

    执行流程：
    1. 根据平台和平台用户 ID 查询访客
    2. 如果不存在，创建新访客并创建频道
    3. 如果存在，更新信息（昵称、头像）
    4. 重置已关闭访客的状态

    设计考量：
    - 自动处理访客信息更新
    - 已关闭的访客重新打开时重置状态
    - 返回是否发生了更新，便于调用方处理

    Args:
        db: 数据库会话
        platform: 平台对象
        platform_open_id: 平台用户 ID
        nickname: 昵称（可选）
        avatar_url: 头像 URL（可选）

    Returns:
        tuple[Visitor, bool]: (访客对象, 是否发生了更新)
    """
    # 查询已存在的访客
    visitor = (
        db.query(Visitor)
        .filter(
            Visitor.platform_id == platform.id,
            Visitor.platform_open_id == platform_open_id,
            Visitor.deleted_at.is_(None),
        )
        .first()
    )

    if not visitor:
        # 创建新访客（同时创建频道）
        visitor = await visitor_service.create_visitor_with_channel(
            db=db,
            platform=platform,
            platform_open_id=platform_open_id,
            name=nickname,  # 同时设置 name
            nickname=nickname,
            avatar_url=avatar_url,
        )
        return visitor, True
    else:
        # 更新访客信息（如果提供且发生变化）
        changed = False

        # 更新昵称
        if nickname:
            if visitor.nickname != nickname:
                visitor.nickname = nickname
                changed = True
            if visitor.name != nickname:
                visitor.name = nickname
                changed = True
            # 同步更新 nickname_zh 以确保两个字段一致
            if visitor.nickname_zh != nickname:
                visitor.nickname_zh = nickname
                changed = True

        # 更新头像
        if avatar_url and visitor.avatar_url != avatar_url:
            visitor.avatar_url = avatar_url
            changed = True

        # 重置已关闭访客的状态（允许重新进入服务）
        if visitor.service_status == VisitorServiceStatus.CLOSED.value:
            visitor.service_status = VisitorServiceStatus.NEW.value
            changed = True
            logger.debug(f"Reset visitor {visitor.id} status from CLOSED to NEW")

        if changed:
            visitor.updated_at = datetime.utcnow()
            db.commit()

    return visitor, changed