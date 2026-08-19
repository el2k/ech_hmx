# -*- coding: utf-8 -*-
"""Conversation management endpoints for WuKongIM."""
# 模块说明：WuKongIM 会话管理端点，提供会话列表同步、消息同步、未读数设置、会话删除等功能。

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload, aliased

from app.core.database import get_db
from app.core.logging import get_logger
from app.core.security import get_current_active_user, get_user_language, UserLanguage, require_permission
from app.models import (
    Staff,
    StaffRole,
    Visitor,
    VisitorTag,
    VisitorWaitingQueue,
    WaitingStatus,
    VisitorSession,
    SessionStatus,
    VisitorServiceStatus,
    ChannelMemoryClearance,
    ClearanceUserType,
)
from app.utils.manual_service_tag import MANUAL_SERVICE_TAG_ID
from app.schemas.base import PaginationMetadata
from app.schemas.wukongim import (
    ChannelInfo,
    WuKongIMChannelMessageSyncRequest,
    WuKongIMChannelMessageSyncResponse,
    WuKongIMConversation,
    WuKongIMConversationSyncRequest,
    WuKongIMConversationSyncResponse,
    WuKongIMConversationWithChannelsResponse,
    WuKongIMDeleteConversationRequest,
    WuKongIMSetUnreadRequest,
)
from app.schemas.visitor import VisitorResponse, resolve_visitor_display_name, set_visitor_display_nickname
from app.api.v1.endpoints.channels import _build_enriched_visitor_payload
from app.services.wukongim_client import wukongim_client
from app.utils.encoding import build_visitor_channel_id, parse_visitor_channel_id
from app.utils.const import CHANNEL_TYPE_CUSTOMER_SERVICE

logger = get_logger("api.conversations")
router = APIRouter()


# ============================================================================
# 辅助函数：为会话构建频道信息
# ============================================================================

async def _build_channels_for_conversations(
    db: Session,
    conversations: List[WuKongIMConversation],
    project_id: UUID,
    user_language: UserLanguage = "en",
    accept_language: Optional[str] = None,
    include_closed_and_queued: bool = False,
) -> List[ChannelInfo]:
    """
    为会话列表构建频道信息列表（批量查询优化）。

    此函数从 WuKongIM 会话列表中提取访客频道信息，批量查询数据库获取访客详情，
    避免 N+1 查询问题，提高性能。

    Args:
        db: 数据库会话
        conversations: WuKongIM 会话列表
        project_id: 当前项目 ID
        user_language: 用户语言偏好
        accept_language: Accept-Language 头
        include_closed_and_queued: 是否包含已关闭和排队中的访客

    Returns:
        List[ChannelInfo]: 频道信息列表
    """
    if not conversations:
        return []
    
    # ---------- 1. 提取访客 ID ----------
    visitor_ids: List[UUID] = []
    channel_id_to_visitor_id: Dict[str, UUID] = {}
    
    for conv in conversations:
        channel_type = conv.channel_type
        channel_id = conv.channel_id
        if channel_type == CHANNEL_TYPE_CUSTOMER_SERVICE and channel_id:
            try:
                visitor_id = parse_visitor_channel_id(channel_id)  # Base62 解码
                visitor_ids.append(visitor_id)
                channel_id_to_visitor_id[channel_id] = visitor_id
            except ValueError:
                # 无效的频道 ID 格式，跳过
                continue
    
    if not visitor_ids:
        return []
    
    # ---------- 2. 批量查询访客（单次查询） ----------
    visitor_query = (
        db.query(Visitor)
        .options(
            selectinload(Visitor.platform),
            selectinload(Visitor.visitor_tags).selectinload(VisitorTag.tag),
            selectinload(Visitor.ai_profile),
            selectinload(Visitor.ai_insight),
            selectinload(Visitor.system_info),
        )
        .filter(
            Visitor.id.in_(visitor_ids),
            Visitor.project_id == project_id,
            Visitor.deleted_at.is_(None),
        )
    )
    if not include_closed_and_queued:
        # 默认过滤掉已关闭和排队中的访客
        visitor_query = visitor_query.filter(
            Visitor.service_status.notin_([
                VisitorServiceStatus.CLOSED.value,
                VisitorServiceStatus.QUEUED.value,
            ])
        )
    visitors = visitor_query.all()
    
    # 创建访客查找映射
    visitor_map: Dict[UUID, Visitor] = {v.id: v for v in visitors}
    
    # ---------- 3. 批量查询开放会话 ----------
    open_sessions = (
        db.query(VisitorSession)
        .filter(
            VisitorSession.visitor_id.in_(visitor_ids),
            VisitorSession.project_id == project_id,
            VisitorSession.status == SessionStatus.OPEN.value,
        )
        .all()
    )
    
    # 创建会话查找映射 (visitor_id -> staff_id)
    visitor_to_staff: Dict[UUID, UUID] = {}
    for session in open_sessions:
        if session.staff_id:
            visitor_to_staff[session.visitor_id] = session.staff_id
    
    # ---------- 4. 构建频道信息列表 ----------
    channels: List[ChannelInfo] = []
    
    for conv in conversations:
        channel_type = conv.channel_type
        channel_id = conv.channel_id
        
        if channel_type != CHANNEL_TYPE_CUSTOMER_SERVICE:
            continue
            
        visitor_id = channel_id_to_visitor_id.get(channel_id)
        if not visitor_id:
            continue
            
        visitor = visitor_map.get(visitor_id)
        if not visitor:
            continue
        
        # 构建丰富的访客响应（与 /channels/info 保持一致）
        visitor_payload = _build_enriched_visitor_payload(
            visitor=visitor,
            db=db,
            project_id=project_id,
            accept_language=accept_language,
            user_language=user_language,
        )
        
        # 根据用户语言设置显示昵称
        set_visitor_display_nickname(visitor_payload, user_language)
        
        # 添加已分配客服 ID
        assigned_staff_id = visitor_to_staff.get(visitor_id)
        extra_data = visitor_payload.model_dump()
        if assigned_staff_id:
            extra_data["assigned_staff_id"] = str(assigned_staff_id)
        
        # 解析显示名称
        name = resolve_visitor_display_name(
            name=visitor.name,
            nickname=visitor.nickname,
            nickname_zh=visitor.nickname_zh,
            language=user_language,
            fallback="Unknown Visitor",
        )
        
        channel_info = ChannelInfo(
            name=name,
            avatar=visitor_payload.avatar_url or "",
            channel_id=channel_id,
            channel_type=channel_type,
            entity_type="visitor",
            extra=extra_data,
        )
        channels.append(channel_info)
    
    return channels


# ============================================================================
# 响应模型
# ============================================================================

class WuKongIMConversationPaginatedResponse(BaseModel):
    """WuKongIM 会话分页响应。"""
    
    conversations: List[WuKongIMConversation] = Field(
        default_factory=list,
        description="会话列表"
    )
    pagination: PaginationMetadata = Field(..., description="分页元数据")


class WuKongIMConversationWithChannelsPaginatedResponse(BaseModel):
    """WuKongIM 会话分页响应（含频道详情）。"""

    conversations: List[WuKongIMConversation] = Field(
        default_factory=list,
        description="会话列表",
    )
    channels: List[ChannelInfo] = Field(
        default_factory=list,
        description="每个会话对应的频道信息列表",
    )
    pagination: PaginationMetadata = Field(..., description="分页元数据")


# ============================================================================
# 1. 同步我的会话列表
# ============================================================================

@router.post(
    "/my",
    response_model=WuKongIMConversationWithChannelsResponse,
    summary="同步我的会话列表",
    description="同步当前客服在 WuKongIM 中的所有会话列表（包含历史会话），包含最近消息和频道信息。",
)
async def sync_my_conversations(
    http_request: Request,
    request: WuKongIMConversationSyncRequest,
    tag_ids: Optional[List[str]] = Query(
        default=None,
        description="访客标签ID（Base64），支持多个 tag_id（OR 关系）。提供后仅返回匹配标签的访客会话。",
    ),
    manual_service_contain: bool = Query(
        default=False,
        description="如果为 true，则仅返回 tags 中包含「转人工(Manual Service)」标签的访客会话（可与 tag_ids 组合，AND 关系）。",
    ),
    db: Session = Depends(get_db),
    current_user: Staff = Depends(get_current_active_user),
    user_language: UserLanguage = Depends(get_user_language),
) -> WuKongIMConversationWithChannelsResponse:
    """
    同步当前客服的会话列表。

    直接从 WuKongIM 获取当前客服参与的所有会话及其最近消息记录，
    包括已关闭的历史会话。同时返回每个会话对应的频道详细信息。

    支持按访客标签过滤：
        - tag_ids: 多个标签 ID（OR 关系）
        - manual_service_contain: 是否必须包含「转人工」标签（AND 关系）
    """
    staff_uid = f"{current_user.id}-staff"

    logger.info(
        f"Staff {current_user.username} syncing my conversations",
        extra={
            "staff_username": current_user.username,
            "staff_uid": staff_uid,
            "msg_count": request.msg_count,
        }
    )

    try:
        # ---------- 1. 从 WuKongIM 获取会话 ----------
        conversations = await wukongim_client.sync_conversations(
            uid=staff_uid,
            last_msg_seqs=request.last_msg_seqs,
            msg_count=request.msg_count,
        )

        logger.info(f"Successfully synced {len(conversations)} conversations for staff {current_user.username}")

        # ---------- 2. 可选标签过滤 ----------
        tag_ids_resolved = [t for t in (tag_ids or []) if t]
        tag_filter_enabled = bool(tag_ids_resolved) or manual_service_contain
        
        if tag_filter_enabled:
            # 收集所有访客 ID
            visitor_id_by_channel_id: Dict[str, UUID] = {}
            visitor_ids_in_convs: List[UUID] = []
            for conv in conversations:
                if conv.channel_type != CHANNEL_TYPE_CUSTOMER_SERVICE or not conv.channel_id:
                    continue
                try:
                    v_id = parse_visitor_channel_id(conv.channel_id)
                except Exception:
                    continue
                visitor_id_by_channel_id[conv.channel_id] = v_id
                visitor_ids_in_convs.append(v_id)

            # 批量查询访客标签
            if visitor_ids_in_convs:
                rows = (
                    db.query(VisitorTag.visitor_id, VisitorTag.tag_id)
                    .filter(
                        VisitorTag.project_id == current_user.project_id,
                        VisitorTag.deleted_at.is_(None),
                        VisitorTag.visitor_id.in_(visitor_ids_in_convs),
                    )
                    .all()
                )
                visitor_to_tags: Dict[UUID, set[str]] = {}
                for v_id, t_id in rows:
                    visitor_to_tags.setdefault(v_id, set()).add(t_id)

                # 应用标签过滤条件
                allowed_visitor_ids: set[UUID] = set()
                for v_id in visitor_ids_in_convs:
                    tags_set = visitor_to_tags.get(v_id, set())
                    has_manual = MANUAL_SERVICE_TAG_ID in tags_set
                    has_any = bool(tags_set.intersection(tag_ids_resolved)) if tag_ids_resolved else True
                    if (not manual_service_contain or has_manual) and has_any:
                        allowed_visitor_ids.add(v_id)

                # 过滤会话
                conversations = [
                    conv
                    for conv in conversations
                    if conv.channel_type == CHANNEL_TYPE_CUSTOMER_SERVICE
                    and conv.channel_id
                    and visitor_id_by_channel_id.get(conv.channel_id) in allowed_visitor_ids
                ]
            else:
                conversations = []

        # ---------- 3. 构建频道信息列表 ----------
        # 此步骤会过滤掉已关闭和排队中的访客
        channels = await _build_channels_for_conversations(
            db=db,
            conversations=conversations,
            project_id=current_user.project_id,
            user_language=user_language,
            accept_language=http_request.headers.get("Accept-Language"),
        )
        
        # 仅过滤访客（客服频道）会话，非访客会话（如员工私聊）保持不变
        valid_channel_ids = {ch.channel_id for ch in channels}
        filtered_conversations = [
            conv
            for conv in conversations
            if conv.channel_type != CHANNEL_TYPE_CUSTOMER_SERVICE
            or (conv.channel_id in valid_channel_ids)
        ]

        return WuKongIMConversationWithChannelsResponse(
            conversations=filtered_conversations,
            channels=channels,
        )

    except Exception as e:
        logger.error(f"Failed to sync conversations for staff {current_user.username}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync conversations"
        )


# ============================================================================
# 2. 获取所有服务过的访客会话
# ============================================================================

@router.post(
    "/all",
    response_model=WuKongIMConversationPaginatedResponse,
    summary="获取所有服务过的访客会话",
    description="获取当前客服服务过的所有访客会话列表（基于 VisitorSession 表，包括已关闭的会话），支持分页。",
)
async def sync_all_conversations(
    msg_count: int = Query(default=20, ge=1, le=100, description="每个会话返回的最近消息数量"),
    only_completed_recent: bool = Query(
        default=False,
        description="如果为 true，则仅返回「已完成(Closed)」的最近会话（按每个访客最近一次已关闭会话时间排序）",
    ),
    limit: int = Query(default=20, ge=1, le=100, description="每页返回的会话数量"),
    offset: int = Query(default=0, ge=0, description="跳过的会话数量"),
    db: Session = Depends(get_db),
    current_user: Staff = Depends(get_current_active_user),
) -> WuKongIMConversationPaginatedResponse:
    """
    获取当前客服服务过的所有访客会话（支持分页）。

    查询 VisitorSession 表中 staff_id 为当前客服的所有会话（包括已关闭的），
    对访客进行去重后，从 WuKongIM 获取这些会话的最近消息。

    如果当前用户是 admin 角色，则返回项目下所有的会话。
    """
    # 检查是否为管理员
    is_admin = current_user.role == StaffRole.ADMIN.value
    
    # ---------- 1. 构建子查询：每个访客的最新会话时间 ----------
    subquery_base = db.query(
        VisitorSession.visitor_id,
        func.max(VisitorSession.created_at).label("latest_created_at")
    ).filter(
        VisitorSession.visitor_id.isnot(None),
        VisitorSession.staff_id.isnot(None),
    )
    
    if is_admin:
        subquery_base = subquery_base.filter(VisitorSession.project_id == current_user.project_id)
    else:
        subquery_base = subquery_base.filter(VisitorSession.staff_id == current_user.id)
    
    latest_session_subquery = subquery_base.group_by(VisitorSession.visitor_id).subquery()

    # ---------- 2. 连接回最新会话行以过滤状态 ----------
    latest_sessions_query = (
        db.query(
            latest_session_subquery.c.visitor_id,
            latest_session_subquery.c.latest_created_at,
        )
        .join(
            VisitorSession,
            (VisitorSession.visitor_id == latest_session_subquery.c.visitor_id)
            & (VisitorSession.created_at == latest_session_subquery.c.latest_created_at)
            & (VisitorSession.visitor_id.isnot(None))
            & (VisitorSession.staff_id.isnot(None)),
        )
    )
    if is_admin:
        latest_sessions_query = latest_sessions_query.filter(VisitorSession.project_id == current_user.project_id)
    else:
        latest_sessions_query = latest_sessions_query.filter(VisitorSession.staff_id == current_user.id)

    if only_completed_recent:
        # 仅当访客的最新会话是 CLOSED 时才算「已完成」
        latest_sessions_query = latest_sessions_query.filter(VisitorSession.status == SessionStatus.CLOSED.value)

    # 总计数
    total_count = latest_sessions_query.distinct(latest_session_subquery.c.visitor_id).count()
    if total_count == 0:
        return WuKongIMConversationPaginatedResponse(
            conversations=[],
            pagination=PaginationMetadata(
                total=0,
                limit=limit,
                offset=offset,
                has_next=False,
                has_prev=False,
            )
        )
    
    # ---------- 3. 分页获取访客 ID ----------
    paginated_visitor_ids = (
        latest_sessions_query
        .order_by(latest_session_subquery.c.latest_created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    visitor_ids = [row[0] for row in paginated_visitor_ids]
    
    if not visitor_ids:
        return WuKongIMConversationPaginatedResponse(
            conversations=[],
            pagination=PaginationMetadata(
                total=total_count,
                limit=limit,
                offset=offset,
                has_next=False,
                has_prev=offset > 0,
            )
        )
    
    # ---------- 4. 构建频道列表 ----------
    channels: List[dict] = []
    for visitor_id in visitor_ids:
        channel_id = build_visitor_channel_id(visitor_id)
        channels.append({
            "channel_id": channel_id,
            "channel_type": CHANNEL_TYPE_CUSTOMER_SERVICE,
        })
    
    logger.info(
        f"Fetching {'all project' if is_admin else 'staff'} conversations for {len(channels)} visitors (page offset={offset}, limit={limit})",
        extra={
            "staff_id": str(current_user.id),
            "staff_username": current_user.username,
            "is_admin": is_admin,
            "total_unique_visitors": total_count,
            "page_visitor_count": len(channels),
            "msg_count": msg_count,
            "offset": offset,
            "limit": limit,
        }
    )
    
    # ---------- 5. 调用 WuKongIM 同步会话 ----------
    staff_uid = f"{current_user.id}-staff"
    
    try:
        raw_conversations = await wukongim_client.sync_conversations_by_channels(
            uid=staff_uid,
            channels=channels,
            msg_count=msg_count,
        )
        
        # 将所有会话的未读数重置为 0
        conversations = [
            conv.model_copy(update={"unread": 0}) for conv in raw_conversations
        ]
        
        # ---------- 6. 构建分页元数据 ----------
        has_next = (offset + limit) < total_count
        has_prev = offset > 0
        
        return WuKongIMConversationPaginatedResponse(
            conversations=conversations,
            pagination=PaginationMetadata(
                total=total_count,
                limit=limit,
                offset=offset,
                has_next=has_next,
                has_prev=has_prev,
            )
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch conversations for staff {current_user.username}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch conversations",
        )


# ============================================================================
# 3. 获取等待中访客的会话
# ============================================================================

@router.post(
    "/waiting",
    response_model=WuKongIMConversationPaginatedResponse,
    summary="获取等待中访客的会话",
    description="获取所有等待中（未分配）访客的 WuKongIM 会话列表，用于客服查看待接入访客的对话内容，支持分页。",
)
async def sync_waiting_conversations(
    msg_count: int = Query(default=20, ge=1, le=100, description="每个会话返回的最近消息数量"),
    limit: int = Query(default=20, ge=1, le=100, description="每页返回的会话数量"),
    offset: int = Query(default=0, ge=0, description="跳过的会话数量"),
    db: Session = Depends(get_db),
    current_user: Staff = Depends(require_permission("visitors:read")),
) -> WuKongIMConversationPaginatedResponse:
    """
    获取等待中访客的会话列表（支持分页）。

    此接口获取当前项目中所有状态为 WAITING 的访客的 WuKongIM 会话信息，
    包括最近的消息记录。用于客服人员查看待接入访客的对话内容。
    """
    # ---------- 1. 获取等待队列总数 ----------
    total_count = (
        db.query(VisitorWaitingQueue)
        .filter(
            VisitorWaitingQueue.project_id == current_user.project_id,
            VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
            VisitorWaitingQueue.visitor_id.isnot(None),
        )
        .count()
    )
    
    if total_count == 0:
        return WuKongIMConversationPaginatedResponse(
            conversations=[],
            pagination=PaginationMetadata(
                total=0,
                limit=limit,
                offset=offset,
                has_next=False,
                has_prev=False,
            )
        )
    
    # ---------- 2. 分页查询等待中的访客 ----------
    waiting_entries = (
        db.query(VisitorWaitingQueue)
        .filter(
            VisitorWaitingQueue.project_id == current_user.project_id,
            VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
            VisitorWaitingQueue.visitor_id.isnot(None),
        )
        .order_by(VisitorWaitingQueue.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    
    if not waiting_entries:
        return WuKongIMConversationPaginatedResponse(
            conversations=[],
            pagination=PaginationMetadata(
                total=total_count,
                limit=limit,
                offset=offset,
                has_next=False,
                has_prev=offset > 0,
            )
        )
    
    # ---------- 3. 构建频道列表 ----------
    channels: List[dict] = []
    for entry in waiting_entries:
        channel_id = build_visitor_channel_id(entry.visitor_id)
        channels.append({
            "channel_id": channel_id,
            "channel_type": CHANNEL_TYPE_CUSTOMER_SERVICE,
        })
    
    logger.info(
        f"Fetching conversations for {len(channels)} waiting visitors (page offset={offset}, limit={limit})",
        extra={
            "staff_id": str(current_user.id),
            "total_waiting": total_count,
            "page_count": len(channels),
            "msg_count": msg_count,
            "offset": offset,
            "limit": limit,
        }
    )
    
    # ---------- 4. 调用 WuKongIM 同步会话 ----------
    staff_uid = f"{current_user.id}-staff"
    
    try:
        raw_conversations = await wukongim_client.sync_conversations_by_channels(
            uid=staff_uid,
            channels=channels,
            msg_count=msg_count,
        )
        
        # 将所有会话的未读数重置为 0
        conversations = [
            conv.model_copy(update={"unread": 0}) for conv in raw_conversations
        ]
        
        has_next = (offset + limit) < total_count
        has_prev = offset > 0
        
        return WuKongIMConversationPaginatedResponse(
            conversations=conversations,
            pagination=PaginationMetadata(
                total=total_count,
                limit=limit,
                offset=offset,
                has_next=has_next,
                has_prev=has_prev,
            )
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch waiting visitors conversations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch waiting visitors conversations",
        )


# ============================================================================
# 4. 按访客标签获取最近会话
# ============================================================================

@router.get(
    "/by-tags/recent",
    response_model=WuKongIMConversationWithChannelsPaginatedResponse,
    summary="按访客标签获取最近会话",
    description="按访客标签（tag_id，支持多个）筛选访客，并返回这些访客的最近会话列表（按最新会话时间倒序），支持分页。",
)
async def sync_recent_conversations_by_visitor_tags(
    http_request: Request,
    tag_ids: Optional[List[str]] = Query(default=None, description="访客标签ID（Base64），支持多个 tag_id（OR 关系）"),
    manual_service_contain: bool = Query(
        default=False,
        description="如果为 true，则要求访客 tags 中包含「转人工(Manual Service)」标签（可与 tag_ids 组合，AND 关系）",
    ),
    msg_count: int = Query(default=1, ge=1, le=100, description="每个会话返回的最近消息数量（默认 1）"),
    limit: int = Query(default=20, ge=1, le=100, description="每页返回的会话数量"),
    offset: int = Query(default=0, ge=0, description="跳过的会话数量"),
    db: Session = Depends(get_db),
    current_user: Staff = Depends(require_permission("visitors:read")),
    user_language: UserLanguage = Depends(get_user_language),
) -> WuKongIMConversationWithChannelsPaginatedResponse:
    """
    按访客标签筛选访客并获取最近会话。

    此接口用于客服根据标签快速定位特定访客群体，如「VIP用户」或「需要转人工」的访客。

    管理员看到项目下所有会话，普通员工只看到自己的会话。
    """
    # 检查是否为管理员
    is_admin = current_user.role == StaffRole.ADMIN.value

    tag_ids_resolved = [t for t in (tag_ids or []) if t]
    if not tag_ids_resolved and not manual_service_contain:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tag_ids is required")

    # ---------- 1. 构建子查询：按标签筛选访客的最新会话 ----------
    vt_filter = aliased(VisitorTag)
    vt_manual = aliased(VisitorTag)

    subquery_base = (
        db.query(
            VisitorSession.visitor_id,
            func.max(VisitorSession.created_at).label("latest_created_at"),
        )
        .filter(
            VisitorSession.project_id == current_user.project_id,
            VisitorSession.visitor_id.isnot(None),
            VisitorSession.staff_id.isnot(None),
        )
    )

    # tag_ids 过滤（OR 关系）
    if tag_ids_resolved:
        subquery_base = subquery_base.join(
            vt_filter,
            (vt_filter.visitor_id == VisitorSession.visitor_id)
            & (vt_filter.project_id == current_user.project_id)
            & (vt_filter.deleted_at.is_(None))
            & (vt_filter.tag_id.in_(tag_ids_resolved)),
        )

    # 必须包含「转人工」标签（AND 关系）
    if manual_service_contain:
        subquery_base = subquery_base.join(
            vt_manual,
            (vt_manual.visitor_id == VisitorSession.visitor_id)
            & (vt_manual.project_id == current_user.project_id)
            & (vt_manual.deleted_at.is_(None))
            & (vt_manual.tag_id == MANUAL_SERVICE_TAG_ID),
        )

    if not is_admin:
        subquery_base = subquery_base.filter(VisitorSession.staff_id == current_user.id)

    latest_session_subquery = subquery_base.group_by(VisitorSession.visitor_id).subquery()

    # ---------- 2. 总计数 ----------
    total_count = db.query(latest_session_subquery.c.visitor_id).count()
    if total_count == 0:
        return WuKongIMConversationWithChannelsPaginatedResponse(
            conversations=[],
            channels=[],
            pagination=PaginationMetadata(
                total=0,
                limit=limit,
                offset=offset,
                has_next=False,
                has_prev=False,
            ),
        )

    # ---------- 3. 分页获取访客 ID ----------
    paginated_visitor_ids = (
        db.query(latest_session_subquery.c.visitor_id)
        .order_by(latest_session_subquery.c.latest_created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    visitor_ids = [row[0] for row in paginated_visitor_ids]
    if not visitor_ids:
        return WuKongIMConversationWithChannelsPaginatedResponse(
            conversations=[],
            channels=[],
            pagination=PaginationMetadata(
                total=total_count,
                limit=limit,
                offset=offset,
                has_next=False,
                has_prev=offset > 0,
            ),
        )

    # ---------- 4. 构建频道列表 ----------
    channels_req: List[dict] = [
        {"channel_id": build_visitor_channel_id(visitor_id), "channel_type": CHANNEL_TYPE_CUSTOMER_SERVICE}
        for visitor_id in visitor_ids
    ]

    # ---------- 5. 调用 WuKongIM 同步会话 ----------
    staff_uid = f"{current_user.id}-staff"
    try:
        raw_conversations = await wukongim_client.sync_conversations_by_channels(
            uid=staff_uid,
            channels=channels_req,
            msg_count=msg_count,
        )
        conversations = [conv.model_copy(update={"unread": 0}) for conv in raw_conversations]

        # 构建频道信息（包含已关闭和排队中的访客）
        channel_infos = await _build_channels_for_conversations(
            db=db,
            conversations=conversations,
            project_id=current_user.project_id,
            user_language=user_language,
            accept_language=http_request.headers.get("Accept-Language"),
            include_closed_and_queued=True,
        )

        valid_channel_ids = {ch.channel_id for ch in channel_infos}
        filtered_conversations = [
            conv for conv in conversations if (conv.channel_type != CHANNEL_TYPE_CUSTOMER_SERVICE) or (conv.channel_id in valid_channel_ids)
        ]

        has_next = (offset + limit) < total_count
        has_prev = offset > 0

        return WuKongIMConversationWithChannelsPaginatedResponse(
            conversations=filtered_conversations,
            channels=channel_infos,
            pagination=PaginationMetadata(
                total=total_count,
                limit=limit,
                offset=offset,
                has_next=has_next,
                has_prev=has_prev,
            ),
        )
    except Exception as e:
        logger.error(f"Failed to fetch conversations by tags: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch conversations by tags",
        )


# ============================================================================
# 5. 设置会话未读数
# ============================================================================

@router.put(
    "/unread",
    summary="设置会话未读数",
    description="设置指定会话的未读消息数量。",
)
async def set_conversation_unread(
    request: WuKongIMSetUnreadRequest,
    current_user: Staff = Depends(get_current_active_user),
) -> Dict[str, str]:
    """
    设置会话的未读消息数量。

    用于客服手动标记会话为已读/未读状态。
    """
    staff_uid = f"{current_user.id}-staff"

    logger.info(
        f"Staff {current_user.username} setting unread count for conversation",
        extra={
            "staff_username": current_user.username,
            "staff_uid": staff_uid,
            "channel_id": request.channel_id,
            "channel_type": request.channel_type,
            "unread": request.unread,
        }
    )

    try:
        await wukongim_client.set_conversation_unread(
            uid=staff_uid,
            channel_id=request.channel_id,
            channel_type=request.channel_type,
            unread=request.unread,
        )

        return {"message": "Unread count updated successfully"}

    except Exception as e:
        logger.error(f"Failed to set unread count for staff {current_user.username}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set unread count"
        )


# ============================================================================
# 6. 删除会话
# ============================================================================

@router.delete(
    "",
    summary="删除会话",
    description="从会话列表中删除指定的会话。",
)
async def delete_conversation(
    request: WuKongIMDeleteConversationRequest,
    current_user: Staff = Depends(get_current_active_user),
) -> Dict[str, str]:
    """
    从会话列表中删除指定的会话。

    删除后，该会话将从客服的会话列表中消失，但聊天记录仍然保留。
    """
    staff_uid = f"{current_user.id}-staff"

    logger.info(
        f"Staff {current_user.username} deleting conversation",
        extra={
            "staff_username": current_user.username,
            "staff_uid": staff_uid,
            "channel_id": request.channel_id,
            "channel_type": request.channel_type,
        }
    )

    try:
        await wukongim_client.delete_conversation(
            uid=staff_uid,
            channel_id=request.channel_id,
            channel_type=request.channel_type,
        )

        return {"message": "Conversation deleted successfully"}

    except Exception as e:
        logger.error(f"Failed to delete conversation for staff {current_user.username}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete conversation"
        )


# ============================================================================
# 7. 同步频道消息（含记忆清除处理）
# ============================================================================

@router.post(
    "/messages",
    response_model=WuKongIMChannelMessageSyncResponse,
    summary="同步频道消息",
    description="同步指定频道的历史消息记录。",
)
async def sync_channel_messages(
    request: WuKongIMChannelMessageSyncRequest,
    current_user: Staff = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> WuKongIMChannelMessageSyncResponse:
    """
    同步指定频道的历史消息记录。

    此接口会检查是否有记忆清除记录（ChannelMemoryClearance），
    如果有，则自动调整 start_message_seq 以跳过已清除的消息。

    这样用户在点击「清除记忆」后，再拉取历史消息时不会看到被清除的内容。
    """
    staff_uid = f"{current_user.id}-staff"

    # ---------- 1. 检查记忆清除记录 ----------
    clearance = db.query(ChannelMemoryClearance).filter(
        ChannelMemoryClearance.user_id == current_user.id,
        ChannelMemoryClearance.user_type == ClearanceUserType.STAFF.value,
        ChannelMemoryClearance.channel_id == request.channel_id,
        ChannelMemoryClearance.channel_type == request.channel_type,
    ).first()

    # ---------- 2. 调整起始消息序列号 ----------
    effective_start_seq = request.start_message_seq
    if clearance and clearance.cleared_message_seq > effective_start_seq:
        # 从清除位置的下一条消息开始
        effective_start_seq = clearance.cleared_message_seq + 1

    logger.info(
        f"Staff {current_user.username} syncing channel messages",
        extra={
            "staff_username": current_user.username,
            "staff_uid": staff_uid,
            "channel_id": request.channel_id,
            "channel_type": request.channel_type,
            "start_message_seq": request.start_message_seq,
            "effective_start_seq": effective_start_seq,
            "end_message_seq": request.end_message_seq,
            "limit": request.limit,
            "pull_mode": request.pull_mode,
            "has_clearance": clearance is not None,
        }
    )

    # ---------- 3. 调用 WuKongIM 同步消息 ----------
    try:
        result = await wukongim_client.sync_channel_messages(
            login_uid=staff_uid,
            channel_id=request.channel_id,
            channel_type=request.channel_type,
            start_message_seq=effective_start_seq,
            end_message_seq=request.end_message_seq,
            limit=request.limit,
            pull_mode=request.pull_mode,
            include_event_meta=1,
            event_summary_mode="full",
        )

        message_count = len(result.messages)
        logger.info(f"Successfully synced {message_count} channel messages for staff {current_user.username}")

        return result

    except Exception as e:
        logger.error(f"Failed to sync channel messages for staff {current_user.username}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync channel messages"
        )