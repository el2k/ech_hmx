# -*- coding: utf-8 -*-
"""Channel information endpoints."""
# 模块说明：频道信息端点，根据 channel_id 和 channel_type 获取频道的详细信息。
# 频道（Channel）是 WuKongIM 中的通信通道，用于访客、员工、AI Agent 之间的消息传递。

from typing import Any, Dict, Optional, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.database import get_db
from app.core.security import verify_token, get_user_language, UserLanguage
from app.models import Staff, Visitor, VisitorTag, VisitorActivity, Platform, VisitorSession, SessionStatus
from app.schemas.visitor import (
    VisitorResponse,
    VisitorAIProfileResponse,
    VisitorAIInsightResponse,
    VisitorSystemInfoResponse,
    VisitorActivityResponse,
    set_visitor_display_nickname,
    resolve_visitor_display_name,
    populate_visitor_ai_settings,
)
from app.schemas import TagResponse
from app.schemas.tag import set_tag_list_display_name
from app.services.ai_client import ai_client

from app.utils.const import CHANNEL_TYPE_CUSTOMER_SERVICE
from app.utils.encoding import parse_visitor_channel_id
from app.utils.intent import localize_visitor_response_intent


router = APIRouter()

# ------------------- 频道ID后缀常量 -------------------
# 用于区分不同类型的个人频道
STAFF_SUFFIX = "-staff"    # 员工个人频道后缀
AGENT_SUFFIX = "-agent"    # AI Agent 个人频道后缀
VISITOR_SUFFIX = "-vtr"    # 访客个人频道后缀


# ------------------- 响应模型 -------------------

class ChannelInfoResponse(BaseModel):
    """
    频道信息响应模型。
    
    根据频道类型和实体类型，extra 字段包含不同内容。
    """
    name: str = Field(..., description="Channel display name")
    avatar: str = Field(..., description="Channel avatar URL")
    channel_id: str = Field(..., description="WuKongIM channel identifier")
    channel_type: int = Field(..., description="Channel type: 1 (personal), 251 (customer service)")
    entity_type: Literal["visitor", "staff", "agent"] = Field(
        ..., description="Entity type represented by this channel: 'visitor', 'staff', or 'agent'"
    )
    extra: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "Scenario 1 – Customer Service Channel (channel_type == 251):\n"
            "- extra contains the complete VisitorResponse as a dictionary.\n\n"
            "Scenario 2 – Personal Channel - Staff (channel_type == 1 AND channel_id ends with '-staff'):\n"
            "- extra contains staff metadata: staff_id, username, role.\n\n"
            "Scenario 3 – Personal Channel - Agent (channel_type == 1 AND channel_id ends with '-agent'):\n"
            "- extra contains agent metadata from AI service: id, name, instruction, model, is_default, config, tools, collections.\n\n"
            "Scenario 4 – Personal Channel - Visitor (channel_type == 1 AND channel_id does NOT end with '-staff' or '-agent'):\n"
            "- Same as Scenario 1: extra contains the complete VisitorResponse as a dictionary."
        ),
        json_schema_extra={
            "examples": [
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "platform_id": "00000000-0000-0000-0000-000000000001",
                    "platform_type": "website",
                    "name": "Jane Doe",
                    "is_online": True
                },
                {
                    "staff_id": "7b7d3d6e-8a7d-4a23-9a2f-1f1c9c7f8f00",
                    "username": "support.alice",
                    "role": "user"
                },
                {
                    "id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
                    "name": "Customer Support Agent",
                    "model": "gpt-4",
                    "is_default": True,
                    "tools": [],
                    "collections": []
                },
            ]
        },
    )


# ------------------- 辅助构建函数 -------------------

def _build_enriched_visitor_payload(
    visitor: Visitor,
    db: Session,
    project_id: UUID,
    accept_language: Optional[str] = None,
    user_language: UserLanguage = "en",
) -> VisitorResponse:
    """
    构建丰富的访客负载数据。
    
    包含：
        - 访客基本信息
        - 标签列表
        - AI 画像
        - AI 洞察
        - 系统信息
        - 最近活动（最多10条）
        - 已分配的客服员工 ID
    
    Args:
        visitor: 访客对象
        db: 数据库会话
        project_id: 项目ID
        accept_language: 接受语言头
        user_language: 用户语言
    
    Returns:
        VisitorResponse: 完整的访客响应对象
    """
    # ---------- 1. 获取并处理标签 ----------
    active_tags = [
        vt.tag
        for vt in visitor.visitor_tags
        if vt.deleted_at is None and vt.tag and vt.tag.deleted_at is None
    ]
    tag_responses = [TagResponse.model_validate(tag) for tag in active_tags]
    set_tag_list_display_name(tag_responses, user_language)  # 根据语言设置标签显示名称

    # ---------- 2. 获取 AI 相关数据 ----------
    ai_profile_response = (
        VisitorAIProfileResponse.model_validate(visitor.ai_profile) if visitor.ai_profile else None
    )
    ai_insight_response = (
        VisitorAIInsightResponse.model_validate(visitor.ai_insight) if visitor.ai_insight else None
    )
    system_info_response = (
        VisitorSystemInfoResponse.model_validate(visitor.system_info) if visitor.system_info else None
    )

    # ---------- 3. 获取最近活动 ----------
    recent_activities = (
        db.query(VisitorActivity)
        .filter(
            VisitorActivity.visitor_id == visitor.id,
            VisitorActivity.project_id == project_id,
            VisitorActivity.deleted_at.is_(None),
        )
        .order_by(VisitorActivity.occurred_at.desc())
        .limit(10)
        .all()
    )
    recent_activity_responses = [
        VisitorActivityResponse.model_validate(activity) for activity in recent_activities
    ]

    # ---------- 4. 获取当前开放会话的客服 ----------
    open_session = (
        db.query(VisitorSession)
        .filter(
            VisitorSession.visitor_id == visitor.id,
            VisitorSession.project_id == project_id,
            VisitorSession.status == SessionStatus.OPEN.value,
        )
        .order_by(VisitorSession.created_at.desc())
        .first()
    )
    assigned_staff_id = open_session.staff_id if open_session else None

    # ---------- 5. 组装响应 ----------
    visitor_payload = VisitorResponse.model_validate(visitor).model_copy(
        update={
            "tags": tag_responses,
            "ai_profile": ai_profile_response,
            "ai_insights": ai_insight_response,
            "system_info": system_info_response,
            "recent_activities": recent_activity_responses,
            "assigned_staff_id": assigned_staff_id,
        }
    )
    # 填充 AI 设置（从平台配置继承）
    populate_visitor_ai_settings(visitor_payload, visitor.platform)
    # 本地化意图数据
    localize_visitor_response_intent(visitor_payload, accept_language)

    return visitor_payload


def _get_visitor_with_relations(db: Session, visitor_id: UUID, project_id: UUID) -> Optional[Visitor]:
    """
    查询访客并预加载所有关联关系。
    
    使用 selectinload 预加载以避免 N+1 查询问题。
    
    Args:
        db: 数据库会话
        visitor_id: 访客ID
        project_id: 项目ID
    
    Returns:
        Visitor | None: 访客对象或 None
    """
    return (
        db.query(Visitor)
        .options(
            selectinload(Visitor.platform),                      # 平台信息
            selectinload(Visitor.visitor_tags).selectinload(VisitorTag.tag),  # 标签
            selectinload(Visitor.ai_profile),                    # AI 画像
            selectinload(Visitor.ai_insight),                    # AI 洞察
            selectinload(Visitor.system_info),                   # 系统信息
        )
        .filter(
            Visitor.id == visitor_id,
            Visitor.project_id == project_id,
            Visitor.deleted_at.is_(None),
        )
        .first()
    )


def _build_visitor_channel_response(
    visitor: Visitor,
    visitor_payload: VisitorResponse,
    channel_id: str,
    channel_type: int,
    user_language: UserLanguage = "en",
) -> ChannelInfoResponse:
    """构建访客类型的频道响应。"""
    name = resolve_visitor_display_name(
        name=visitor.name,
        nickname=visitor.nickname,
        nickname_zh=visitor.nickname_zh,
        language=user_language,
        fallback="Unknown Visitor",
    )
    avatar = visitor_payload.avatar_url or ""
    return ChannelInfoResponse(
        name=name,
        avatar=avatar,
        channel_id=channel_id,
        channel_type=channel_type,
        entity_type="visitor",
        extra=visitor_payload.model_dump(),
    )


def _build_staff_channel_response(
    staff: Staff,
    channel_id: str,
    channel_type: int,
) -> ChannelInfoResponse:
    """构建员工类型的频道响应。"""
    name = staff.nickname or "Unknown Staff"
    avatar = staff.avatar_url or ""
    extra = {
        "staff_id": str(staff.id),
        "username": staff.username,
        "role": getattr(staff, "role", None),
    }
    return ChannelInfoResponse(
        name=name,
        avatar=avatar,
        channel_id=channel_id,
        channel_type=channel_type,
        entity_type="staff",
        extra=extra,
    )


# ------------------- 主端点 -------------------

@router.get(
    "/info",
    response_model=ChannelInfoResponse,
    # ... 省略文档装饰器以保持简洁 ...
)
async def get_channel_info(
    request: Request,
    channel_id: str,
    channel_type: int,
    platform_api_key: Optional[str] = None,
    x_platform_api_key: Optional[str] = Header(None, alias="X-Platform-API-Key"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db),
    user_language: UserLanguage = Depends(get_user_language),
) -> ChannelInfoResponse:
    """
    获取频道信息。

    根据 channel_id 和 channel_type 返回频道的详细信息。

    认证方式：
        1. JWT Token（员工认证）- 可访问所有同项目频道
        2. Platform API Key（访客端认证）- 仅可访问 staff/agent 个人频道

    Args:
        request: FastAPI 请求对象
        channel_id: WuKongIM 频道ID
        channel_type: 频道类型（1=个人频道，251=客服频道）
        platform_api_key: 查询参数中的 API Key
        x_platform_api_key: 请求头中的 API Key
        credentials: JWT Bearer Token
        db: 数据库会话
        user_language: 用户语言

    Returns:
        ChannelInfoResponse: 频道信息
    """
    accept_language = request.headers.get("Accept-Language")

    # ------------------- 1. 认证 -------------------
    current_user: Optional[Staff] = None
    platform: Optional[Platform] = None

    # 尝试 JWT 认证（员工）
    if credentials and credentials.credentials:
        payload = verify_token(credentials.credentials)
        if payload:
            username = payload.get("sub")
            if username:
                current_user = (
                    db.query(Staff)
                    .filter(Staff.username == username, Staff.deleted_at.is_(None))
                    .first()
                )

    # 如果没有员工认证，尝试 Platform API Key
    if current_user is None:
        api_key = platform_api_key or x_platform_api_key
        if api_key:
            platform = (
                db.query(Platform)
                .filter(Platform.api_key == api_key)
                .first()
            )
            if not platform:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid platform_api_key")
            if platform.deleted_at is not None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform is deleted")
            if platform.is_active is False:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform is disabled")
        else:
            # 两种认证方式都未提供
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    # ------------------- 2. 根据认证方式分发处理 -------------------
    # 员工认证：保持原有行为
    if current_user is not None:
        return await _handle_staff_auth_channel_info(
            channel_id=channel_id,
            channel_type=channel_type,
            current_user=current_user,
            db=db,
            accept_language=accept_language,
            user_language=user_language,
        )

    # Platform API Key 认证：仅限制 staff/agent 个人频道
    if platform is not None:
        return await _handle_platform_auth_channel_info(
            channel_id=channel_id,
            channel_type=channel_type,
            platform=platform,
            db=db,
            user_language=user_language,
        )

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported channel_type")


# ------------------- 认证处理器 -------------------

async def _handle_staff_auth_channel_info(
    channel_id: str,
    channel_type: int,
    current_user: Staff,
    db: Session,
    accept_language: Optional[str],
    user_language: UserLanguage = "en",
) -> ChannelInfoResponse:
    """
    处理员工 JWT 认证的频道信息请求。
    
    员工可以访问：
        - 客服频道（type 251）：访客信息
        - 个人频道（type 1）：staff / agent / visitor
    """
    # ---------- 客服频道 (251) ----------
    if channel_type == CHANNEL_TYPE_CUSTOMER_SERVICE:
        return await _get_customer_service_channel_info(
            channel_id=channel_id,
            channel_type=channel_type,
            project_id=current_user.project_id,
            db=db,
            accept_language=accept_language,
            user_language=user_language,
        )

    # ---------- 个人频道 (1) ----------
    if channel_type == 1:
        # 员工个人频道
        if channel_id.endswith(STAFF_SUFFIX):
            return _get_staff_channel_info(
                channel_id=channel_id,
                channel_type=channel_type,
                project_id=current_user.project_id,
                db=db,
            )

        # Agent 个人频道
        if channel_id.endswith(AGENT_SUFFIX):
            return await _get_agent_channel_info(
                channel_id=channel_id,
                channel_type=channel_type,
                project_id=current_user.project_id,
            )

        # 访客个人频道（有 -vtr 后缀）
        if channel_id.endswith(VISITOR_SUFFIX):
            return _get_personal_visitor_channel_info(
                channel_id=channel_id,
                channel_type=channel_type,
                project_id=current_user.project_id,
                db=db,
                accept_language=accept_language,
                user_language=user_language,
            )

        # 访客个人频道（无后缀，原始 UUID）
        return _get_personal_visitor_channel_info(
            channel_id=channel_id,
            channel_type=channel_type,
            project_id=current_user.project_id,
            db=db,
            accept_language=accept_language,
            user_language=user_language,
        )

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported channel_type")


async def _handle_platform_auth_channel_info(
    channel_id: str,
    channel_type: int,
    platform: Platform,
    db: Session,
    user_language: UserLanguage = "en",
) -> ChannelInfoResponse:
    """
    处理 Platform API Key 认证的频道信息请求。
    
    限制：仅允许访问 staff/agent 个人频道（channel_type==1）
    原因：访客端不应能获取其他访客的敏感信息
    """
    is_staff_channel = channel_type == 1 and channel_id.endswith(STAFF_SUFFIX)
    is_agent_channel = channel_type == 1 and channel_id.endswith(AGENT_SUFFIX)

    # 拒绝非 staff/agent 频道
    if not (is_staff_channel or is_agent_channel):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only staff and agent personal channels are accessible with platform API key",
        )

    # ---------- 员工频道 ----------
    if is_staff_channel:
        staff_id_str = channel_id[:-len(STAFF_SUFFIX)]
        try:
            staff_uuid = UUID(staff_id_str)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid staff_id in channel")

        staff = (
            db.query(Staff)
            .filter(
                Staff.id == staff_uuid,
                Staff.deleted_at.is_(None),
            )
            .first()
        )
        if not staff:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff not found")

        # 确保员工属于同一项目
        if staff.project_id != platform.project_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this channel")

        return _build_staff_channel_response(staff, channel_id, channel_type)

    # ---------- Agent 频道 ----------
    if is_agent_channel:
        return await _get_agent_channel_info(
            channel_id=channel_id,
            channel_type=channel_type,
            project_id=platform.project_id,
        )

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported channel type")


# ------------------- 具体业务处理器 -------------------

async def _get_customer_service_channel_info(
    channel_id: str,
    channel_type: int,
    project_id: UUID,
    db: Session,
    accept_language: Optional[str],
    user_language: UserLanguage = "en",
) -> ChannelInfoResponse:
    """获取客服频道信息（type 251）。"""
    # 解析 Base62 编码的频道ID，提取访客 UUID
    try:
        visitor_uuid = parse_visitor_channel_id(channel_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid channel_id format")

    # 查询访客及其关联数据
    visitor = _get_visitor_with_relations(db, visitor_uuid, project_id)
    if not visitor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visitor not found")

    # 构建丰富响应
    visitor_payload = _build_enriched_visitor_payload(visitor, db, project_id, accept_language, user_language)
    set_visitor_display_nickname(visitor_payload, user_language)
    return _build_visitor_channel_response(visitor, visitor_payload, channel_id, channel_type, user_language)


def _get_staff_channel_info(
    channel_id: str,
    channel_type: int,
    project_id: UUID,
    db: Session,
) -> ChannelInfoResponse:
    """获取员工个人频道信息。"""
    staff_id_str = channel_id[:-len(STAFF_SUFFIX)]
    try:
        staff_uuid = UUID(staff_id_str)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid staff_id in channel")

    staff = (
        db.query(Staff)
        .filter(
            Staff.id == staff_uuid,
            Staff.project_id == project_id,
            Staff.deleted_at.is_(None),
        )
        .first()
    )
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff not found")

    return _build_staff_channel_response(staff, channel_id, channel_type)


async def _get_agent_channel_info(
    channel_id: str,
    channel_type: int,
    project_id: UUID,
) -> ChannelInfoResponse:
    """获取 AI Agent 个人频道信息。"""
    agent_id_str = channel_id[:-len(AGENT_SUFFIX)]
    try:
        agent_uuid = UUID(agent_id_str)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent_id in channel")

    # 从 AI 服务获取 Agent 信息
    try:
        agent_data = await ai_client.get_agent(
            project_id=str(project_id),
            agent_id=str(agent_uuid),
            include_tools=True,
            include_collections=True,
        )
    except HTTPException as e:
        if e.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        raise

    name = agent_data.get("name", "Unknown Agent")
    avatar = agent_data.get("avatar_url", "") or ""

    return ChannelInfoResponse(
        name=name,
        avatar=avatar,
        channel_id=channel_id,
        channel_type=channel_type,
        entity_type="agent",
        extra=agent_data,
    )


def _get_personal_visitor_channel_info(
    channel_id: str,
    channel_type: int,
    project_id: UUID,
    db: Session,
    accept_language: Optional[str],
    user_language: UserLanguage = "en",
) -> ChannelInfoResponse:
    """获取访客个人频道信息（支持有/无 -vtr 后缀）。"""
    # 处理两种格式：原始 UUID 或带 -vtr 后缀
    visitor_id_str = channel_id
    if channel_id.endswith(VISITOR_SUFFIX):
        visitor_id_str = channel_id[:-len(VISITOR_SUFFIX)]
    
    try:
        visitor_uuid = UUID(visitor_id_str)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid visitor_id in channel")

    visitor = _get_visitor_with_relations(db, visitor_uuid, project_id)
    if not visitor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Visitor not found")

    visitor_payload = _build_enriched_visitor_payload(visitor, db, project_id, accept_language, user_language)
    set_visitor_display_nickname(visitor_payload, user_language)
    return _build_visitor_channel_response(visitor, visitor_payload, channel_id, channel_type, user_language)