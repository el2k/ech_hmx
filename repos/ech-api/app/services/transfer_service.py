# =============================================================================
# 模块：访客转接人工服务 (Transfer to human service for visitor)
# =============================================================================
# 该模块提供了将访客转接给人工客服的核心功能，包括：
# 1. 自动分配客服（基于规则、负载均衡、LLM智能选择）
# 2. 直接指定客服
# 3. 无可用客服时加入等待队列
# 4. 从等待队列中分配访客给客服
# 5. 访客重新分配给其他客服
# =============================================================================

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import (
    Visitor,
    VisitorServiceStatus,
    UNASSIGNED_STATUSES,
    VisitorSession,
    VisitorAssignmentHistory,
    VisitorAssignmentRule,
    VisitorWaitingQueue,
    WaitingStatus,
    QueueSource,
    AssignmentSource,
    SessionStatus,
    Staff,
    StaffRole,
    ChannelMember,
)
from app.services.wukongim_client import wukongim_client
from app.utils.encoding import build_visitor_channel_id, build_project_staff_channel_id
from app.utils.const import CHANNEL_TYPE_CUSTOMER_SERVICE, CHANNEL_TYPE_PROJECT_STAFF, MEMBER_TYPE_STAFF

logger = get_logger("services.transfer")


# =============================================================================
# 数据传输对象 (DTO) 定义
# =============================================================================

@dataclass
class TransferResult:
    """
    转接操作结果对象。
    
    Attributes:
        success: 是否成功
        session: 访客会话对象
        assignment_history: 分配历史记录
        assigned_staff_id: 被分配的客服ID（可能为None）
        candidate_staff_ids: 候选客服ID列表
        waiting_queue: 等待队列条目（如果加入队列）
        queue_position: 队列位置
        message: 结果消息
    """
    success: bool
    session: Optional[VisitorSession]
    assignment_history: Optional[VisitorAssignmentHistory]
    assigned_staff_id: Optional[UUID]
    candidate_staff_ids: Optional[List[UUID]]
    waiting_queue: Optional[VisitorWaitingQueue]
    queue_position: Optional[int]
    message: str


@dataclass
class StaffCandidate:
    """
    客服候选人信息。
    
    Attributes:
        id: 客服ID
        name: 姓名
        nickname: 昵称
        description: 描述/擅长领域
        status: 状态 (online/busy/offline)
        current_chat_count: 当前接待中的会话数
    """
    id: UUID
    name: Optional[str]
    nickname: Optional[str]
    description: Optional[str]
    status: str
    current_chat_count: int = 0


@dataclass
class StaffAssignmentResult:
    """
    客服分配结果。
    
    Attributes:
        assigned_staff_id: 被分配的客服ID
        candidate_staff_ids: 所有候选客服ID列表
        llm_response: LLM的原始响应内容
        llm_reasoning: LLM的选择理由
        candidate_scores: 候选客服的评分（如果使用LLM）
        model_used: 使用的模型名称
        prompt_used: 使用的提示词
    """
    assigned_staff_id: Optional[UUID]
    candidate_staff_ids: List[UUID]
    llm_response: Optional[str] = None
    llm_reasoning: Optional[str] = None
    candidate_scores: Optional[dict] = None
    model_used: Optional[str] = None
    prompt_used: Optional[str] = None


# =============================================================================
# 核心转接函数
# =============================================================================

async def transfer_to_staff(
    db: Session,
    visitor_id: UUID,
    project_id: UUID,
    source: AssignmentSource = AssignmentSource.MANUAL,
    visitor_message: Optional[str] = None,
    assigned_by_staff_id: Optional[UUID] = None,
    target_staff_id: Optional[UUID] = None,
    session_id: Optional[UUID] = None,
    platform_id: Optional[UUID] = None,
    notes: Optional[str] = None,
    skip_queue_status_check: bool = False,
    auto_commit: bool = True,
    ai_disabled: Optional[bool] = None,
    add_to_queue_if_no_staff: bool = True,
    send_notification: bool = True,
) -> TransferResult:
    """
    将访客转接给人工客服。

    分配逻辑：
    1. 如果指定了 target_staff_id，直接分配给该客服
    2. 否则，根据规则获取可用客服候选人
    3. 如果候选人数 > 1 且启用了LLM，使用LLM选择
    4. 如果候选人数 > 1 且未启用LLM，使用负载均衡
    5. 如果候选人数 = 1，直接分配
    6. 如果候选人数 = 0 且 add_to_queue_if_no_staff=True，加入等待队列

    Args:
        db: 数据库会话
        visitor_id: 访客ID
        project_id: 项目ID
        source: 转接来源 (MANUAL, LLM, RULE, TRANSFER)
        visitor_message: 触发转接的消息内容
        assigned_by_staff_id: 发起转接的客服ID（手动转接时使用）
        target_staff_id: 指定分配的客服ID（可选）
        session_id: 已存在的会话ID（可选）
        platform_id: 平台ID（创建新会话时使用）
        notes: 附加备注
        skip_queue_status_check: 跳过访客状态检查（队列处理时使用）
        auto_commit: 是否自动提交事务（默认True）
        ai_disabled: 是否禁用AI回复（None=保持当前，True=禁用，False=启用）
        add_to_queue_if_no_staff: 无可用客服时是否加入等待队列（默认True）
        send_notification: 是否发送客服分配系统消息（默认True）

    Returns:
        TransferResult: 包含成功状态和相关对象的转接结果
    """
    llm_response = None
    llm_reasoning = None
    candidate_staff_ids: List[UUID] = []
    candidate_scores: Optional[dict] = None
    model_used: Optional[str] = None
    prompt_used: Optional[str] = None
    waiting_queue_entry: Optional[VisitorWaitingQueue] = None
    queue_position: Optional[int] = None
    no_staff_reason: Optional[str] = None

    try:
        # =====================================================================
        # 步骤1: 验证访客存在并使用行锁防止死锁
        # =====================================================================
        # 使用 FOR UPDATE 确保跨并发事务的一致锁顺序
        visitor = db.query(Visitor).filter(
            Visitor.id == visitor_id,
            Visitor.project_id == project_id,
            Visitor.deleted_at.is_(None),
        ).with_for_update().first()

        if not visitor:
            return TransferResult(
                success=False,
                session=None,
                assignment_history=None,
                assigned_staff_id=None,
                candidate_staff_ids=None,
                waiting_queue=None,
                queue_position=None,
                message="Visitor not found",
            )

        # =====================================================================
        # 步骤1.5: 检查访客是否可以进入队列（仅对非直接分配）
        # =====================================================================
        # 跳过检查的情况：
        # - 指定了 target_staff_id（直接分配）
        # - skip_queue_status_check=True（从队列处理）
        if not target_staff_id and not skip_queue_status_check and not visitor.is_unassigned:
            logger.info(
                f"Visitor {visitor_id} cannot enter queue, current status: {visitor.service_status}"
            )
            return TransferResult(
                success=False,
                session=None,
                assignment_history=None,
                assigned_staff_id=None,
                candidate_staff_ids=None,
                waiting_queue=None,
                queue_position=None,
                message=f"Visitor cannot enter queue (current status: {visitor.service_status}). Only NEW or CLOSED status allowed.",
            )

        # =====================================================================
        # 步骤2: 获取或创建会话
        # =====================================================================
        session = await _get_or_create_session(
            db=db,
            visitor_id=visitor_id,
            project_id=project_id,
            session_id=session_id,
            platform_id=platform_id or visitor.platform_id,
        )

        # =====================================================================
        # 步骤3: 获取项目的分配规则
        # =====================================================================
        assignment_rule = db.query(VisitorAssignmentRule).filter(
            VisitorAssignmentRule.project_id == project_id,
        ).first()

        # =====================================================================
        # 步骤4: 使用 assign_staff 方法确定客服分配
        # =====================================================================
        previous_staff_id = session.staff_id  # 记录之前的客服（用于转接）

        assignment_result = await assign_staff(
            db=db,
            visitor_id=visitor_id,
            project_id=project_id,
            target_staff_id=target_staff_id,
            visitor_message=visitor_message,
            assignment_rule=assignment_rule,
        )

        assigned_staff_id = assignment_result.assigned_staff_id
        candidate_staff_ids = assignment_result.candidate_staff_ids
        llm_response = assignment_result.llm_response
        llm_reasoning = assignment_result.llm_reasoning
        candidate_scores = assignment_result.candidate_scores
        model_used = assignment_result.model_used
        prompt_used = assignment_result.prompt_used

        # =====================================================================
        # 步骤5: 无可用客服时 - 可选加入等待队列
        # =====================================================================
        if not assigned_staff_id and len(candidate_staff_ids) == 0 and add_to_queue_if_no_staff:
            waiting_queue_entry, queue_position = await _add_to_waiting_queue(
                db=db,
                project_id=project_id,
                visitor_id=visitor_id,
                visitor=visitor,
                session_id=session.id,
                visitor_message=visitor_message,
                reason="No available staff",
                assignment_rule=assignment_rule,
                ai_disabled=ai_disabled,
            )

        # =====================================================================
        # 步骤6: 更新访客状态
        # =====================================================================
        # 如果明确提供了 ai_disabled 参数，则更新访客的AI禁用状态
        if ai_disabled is not None:
            visitor.ai_disabled = ai_disabled
        if assigned_staff_id:
            # 有客服分配 - 设置为 ACTIVE（服务中）
            visitor.set_status_active()
        # 如果没有分配（进入队列），状态已在 _add_to_waiting_queue 中设置为 QUEUED

        # =====================================================================
        # 步骤7: 更新会话中的客服ID
        # =====================================================================
        if assigned_staff_id:
            session.staff_id = assigned_staff_id
        session.updated_at = datetime.utcnow()

        # =====================================================================
        # 步骤8: 创建分配历史记录
        # =====================================================================
        assignment_history = _create_assignment_history(
            db=db,
            project_id=project_id,
            visitor_id=visitor_id,
            session_id=session.id,
            assigned_staff_id=assigned_staff_id,
            previous_staff_id=previous_staff_id,
            assigned_by_staff_id=assigned_by_staff_id,
            assignment_rule=assignment_rule,
            source=source,
            visitor_message=visitor_message,
            notes=notes,
            model_used=model_used,
            prompt_used=prompt_used,
            llm_response=llm_response,
            llm_reasoning=llm_reasoning,
            candidate_staff_ids=candidate_staff_ids,
            candidate_scores=candidate_scores,
        )

        # =====================================================================
        # 步骤9: 刷新并提交事务，释放行锁
        # =====================================================================
        # 这可以最小化锁持有时间，防止与并发UPDATE操作（如消息统计更新）发生死锁
        db.flush()
        if auto_commit:
            db.commit()
            db.refresh(session)
            db.refresh(assignment_history)
            db.refresh(visitor)
            if waiting_queue_entry:
                db.refresh(waiting_queue_entry)

        # =====================================================================
        # 步骤10: 将客服添加到访客频道并发送通知
        # =====================================================================
        # 在释放访客锁之后，使用新事务执行
        if assigned_staff_id:
            await _add_staff_to_channel(
                db=db,
                project_id=project_id,
                visitor_id=visitor_id,
                staff_id=assigned_staff_id,
                ai_disabled=visitor.ai_disabled or False,
                send_notification=send_notification,
            )
            # 提交频道成员变更
            if auto_commit:
                db.commit()

        logger.info(
            f"Transferred visitor {visitor_id} to human service. "
            f"Session: {session.id}, Assigned staff: {assigned_staff_id}, Source: {source.value}, "
            f"Candidates: {len(candidate_staff_ids)}, In queue: {waiting_queue_entry is not None}"
        )

        # 根据结果确定消息
        if assigned_staff_id:
            message = "Transfer successful"
        elif waiting_queue_entry:
            message = f"Added to waiting queue at position {queue_position}"
        else:
            message = "Transfer successful, awaiting staff assignment"

        return TransferResult(
            success=True,
            session=session,
            assignment_history=assignment_history,
            assigned_staff_id=assigned_staff_id,
            candidate_staff_ids=candidate_staff_ids,
            waiting_queue=waiting_queue_entry,
            queue_position=queue_position,
            message=message,
        )

    except Exception as e:
        logger.error(f"Error transferring visitor {visitor_id} to human: {e}")
        db.rollback()
        return TransferResult(
            success=False,
            session=None,
            assignment_history=None,
            assigned_staff_id=None,
            candidate_staff_ids=None,
            waiting_queue=None,
            queue_position=None,
            message=f"Transfer failed: {str(e)}",
        )


# =============================================================================
# 客服分配函数
# =============================================================================

async def assign_staff(
    db: Session,
    visitor_id: UUID,
    project_id: UUID,
    target_staff_id: Optional[UUID] = None,
    visitor_message: Optional[str] = None,
    assignment_rule: Optional[VisitorAssignmentRule] = None,
) -> StaffAssignmentResult:
    """
    为访客分配客服。

    分配逻辑：
    1. 如果指定了 target_staff_id，直接分配
    2. 否则，根据规则获取可用客服候选人
    3. 优先分配上次接待该访客的客服（如果有且可用）
    4. 如果候选人数 > 1 且启用了LLM，使用LLM选择
    5. 如果候选人数 > 1 且未启用LLM，使用负载均衡
    6. 如果候选人数 = 1，直接分配
    7. 如果候选人数 = 0，返回None

    Args:
        db: 数据库会话
        visitor_id: 访客ID
        project_id: 项目ID
        target_staff_id: 指定分配的客服ID（可选）
        visitor_message: 触发转接的消息（用于LLM上下文）
        assignment_rule: 项目的分配规则（可选）

    Returns:
        StaffAssignmentResult: 包含分配结果和候选信息
    """
    assigned_staff_id: Optional[UUID] = None
    candidate_staff_ids: List[UUID] = []
    llm_response: Optional[str] = None
    llm_reasoning: Optional[str] = None
    candidate_scores: Optional[dict] = None
    model_used: Optional[str] = None
    prompt_used: Optional[str] = None

    # 获取访客信息（用于LLM上下文）
    visitor = db.query(Visitor).filter(
        Visitor.id == visitor_id,
        Visitor.project_id == project_id,
        Visitor.deleted_at.is_(None),
    ).first()

    # =====================================================================
    # 场景1: 直接分配指定客服
    # =====================================================================
    if target_staff_id:
        staff = db.query(Staff).filter(
            Staff.id == target_staff_id,
            Staff.project_id == project_id,
            Staff.deleted_at.is_(None),
        ).first()

        if staff:
            assigned_staff_id = target_staff_id
            candidate_staff_ids = [target_staff_id]
            logger.info(f"Direct assignment to staff {target_staff_id}")
        else:
            logger.warning(f"Target staff {target_staff_id} not found, will try auto-assignment")

    # =====================================================================
    # 场景2: 自动分配（无指定客服或指定客服不存在）
    # =====================================================================
    if not assigned_staff_id:
        # 获取分配规则（如果未提供）
        if assignment_rule is None:
            assignment_rule = db.query(VisitorAssignmentRule).filter(
                VisitorAssignmentRule.project_id == project_id,
            ).first()

        # 获取可用客服候选人
        candidates = await _get_available_staff_candidates(
            db=db,
            project_id=project_id,
            assignment_rule=assignment_rule,
        )

        candidate_staff_ids = [c.id for c in candidates]

        if len(candidates) == 0:
            # 无可用客服
            logger.info(f"No available staff for project {project_id}")

        elif len(candidates) == 1:
            # 单个候选人，直接分配
            assigned_staff_id = candidates[0].id
            logger.info(f"Single candidate {assigned_staff_id}, assigning directly")

        else:
            # =============================================================
            # 多个候选人 - 首先检查上次接待的客服
            # =============================================================
            last_session = db.query(VisitorSession).join(
                Staff, VisitorSession.staff_id == Staff.id
            ).filter(
                VisitorSession.visitor_id == visitor_id,
                VisitorSession.project_id == project_id,
                VisitorSession.staff_id.isnot(None),
                Staff.deleted_at.is_(None),  # 确保客服未被删除
            ).order_by(VisitorSession.created_at.desc()).first()

            if last_session and last_session.staff_id:
                last_staff_id = last_session.staff_id
                # 检查上次客服是否在可用候选人中
                for candidate in candidates:
                    if candidate.id == last_staff_id:
                        assigned_staff_id = last_staff_id
                        logger.info(
                            f"Prioritizing last serving staff {last_staff_id} for visitor {visitor_id}",
                            extra={
                                "visitor_id": str(visitor_id),
                                "last_staff_id": str(last_staff_id),
                            }
                        )
                        break

            # =============================================================
            # 如果没有上次接待的客服可用，使用LLM或负载均衡
            # =============================================================
            if not assigned_staff_id:
                if assignment_rule and assignment_rule.llm_assignment_enabled and visitor:
                    # 使用LLM选择
                    logger.info(f"Multiple candidates ({len(candidates)}), using LLM assignment")
                    result = await _llm_assign_staff(
                        db=db,
                        project_id=project_id,
                        visitor=visitor,
                        visitor_message=visitor_message,
                        candidates=candidates,
                        assignment_rule=assignment_rule,
                    )
                    assigned_staff_id = result.get("selected_staff_id")
                    llm_response = result.get("llm_response")
                    llm_reasoning = result.get("reasoning")
                    candidate_scores = result.get("scores")
                    model_used = result.get("model_used")
                    prompt_used = result.get("prompt_used")
                else:
                    # 使用负载均衡（选择活跃会话数最少的客服）
                    logger.info(f"Multiple candidates ({len(candidates)}), using load balancing")
                    assigned_staff_id = await _load_balance_assign(candidates)

    return StaffAssignmentResult(
        assigned_staff_id=assigned_staff_id,
        candidate_staff_ids=candidate_staff_ids,
        llm_response=llm_response,
        llm_reasoning=llm_reasoning,
        candidate_scores=candidate_scores,
        model_used=model_used,
        prompt_used=prompt_used,
    )


# =============================================================================
# 等待队列管理函数
# =============================================================================

async def _add_to_waiting_queue(
    db: Session,
    project_id: UUID,
    visitor_id: UUID,
    visitor: Visitor,
    session_id: UUID,
    visitor_message: Optional[str],
    reason: str,
    assignment_rule: Optional[VisitorAssignmentRule],
    ai_disabled: Optional[bool],
) -> tuple[VisitorWaitingQueue, int]:
    """
    将访客添加到等待队列。

    Args:
        db: 数据库会话
        project_id: 项目ID
        visitor_id: 访客ID
        visitor: 访客对象
        session_id: 会话ID
        visitor_message: 触发转接的消息
        reason: 进入队列的原因
        assignment_rule: 分配规则（用于超时配置）
        ai_disabled: AI禁用标志

    Returns:
        tuple: (等待队列条目, 队列位置)
    """
    # 检查是否已在等待队列中
    existing_queue = db.query(VisitorWaitingQueue).filter(
        VisitorWaitingQueue.visitor_id == visitor_id,
        VisitorWaitingQueue.project_id == project_id,
        VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
    ).first()

    if existing_queue:
        logger.info(f"Visitor {visitor_id} already in waiting queue at position {existing_queue.position}")
        return existing_queue, existing_queue.position

    # 计算队列位置（当前等待人数 + 1）
    current_queue_count = db.query(VisitorWaitingQueue).filter(
        VisitorWaitingQueue.project_id == project_id,
        VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
    ).count()
    queue_position = current_queue_count + 1

    # 计算过期时间
    timeout_minutes = settings.QUEUE_DEFAULT_TIMEOUT_MINUTES
    if assignment_rule and assignment_rule.queue_wait_timeout_minutes:
        timeout_minutes = assignment_rule.queue_wait_timeout_minutes
    expired_at = datetime.utcnow() + timedelta(minutes=timeout_minutes)

    # 创建队列条目
    waiting_queue_entry = VisitorWaitingQueue(
        project_id=project_id,
        visitor_id=visitor_id,
        session_id=session_id,
        source=QueueSource.NO_STAFF.value,
        position=queue_position,
        priority=0,
        status=WaitingStatus.WAITING.value,
        visitor_message=visitor_message,
        reason=reason,
        expired_at=expired_at,
        ai_disabled=ai_disabled,
    )
    db.add(waiting_queue_entry)

    # 更新访客状态为 QUEUED（排队中）
    visitor.set_status_queued()

    logger.info(
        f"Added visitor {visitor_id} to waiting queue at position {queue_position}",
        extra={
            "visitor_id": str(visitor_id),
            "queue_position": queue_position,
            "expired_at": str(expired_at),
            "timeout_minutes": timeout_minutes,
        }
    )

    # 发送队列更新事件给客服端
    try:
        staff_channel_id = build_project_staff_channel_id(project_id)
        await wukongim_client.send_queue_updated_event(
            channel_id=staff_channel_id,
            channel_type=CHANNEL_TYPE_PROJECT_STAFF,
            project_id=str(project_id),
            waiting_count=queue_position,
        )
    except Exception as e:
        logger.error(f"Failed to send queue updated event: {e}")

    return waiting_queue_entry, queue_position


# =============================================================================
# 频道管理函数
# =============================================================================

async def _add_staff_to_channel(
    db: Session,
    project_id: UUID,
    visitor_id: UUID,
    staff_id: UUID,
    ai_disabled: bool = False,
    send_notification: bool = True,
) -> None:
    """
    将客服添加到访客频道（同时更新数据库和WuKongIM）。
    会先从频道中移除所有已存在的客服。

    该函数将数据库操作与外部API调用分离，以最小化事务持续时间和防止死锁。

    Args:
        db: 数据库会话
        project_id: 项目ID
        visitor_id: 访客ID
        staff_id: 要添加的客服ID
        ai_disabled: 是否禁用AI（仅当为True时发送消息）
        send_notification: 是否发送客服分配系统消息
    """
    visitor_channel_id = build_visitor_channel_id(visitor_id)
    staff_uid = f"{staff_id}-staff"

    # 收集需要从WuKongIM移除的旧客服UID（在数据库操作之后执行）
    old_staff_uids_to_remove: list[str] = []
    staff_display_name: str | None = None

    # =====================================================================
    # 阶段1: 所有数据库操作优先执行（最小化锁持有时间）
    # =====================================================================

    # 1.1 从频道移除旧的客服成员（仅数据库操作）
    existing_staff_members = db.query(ChannelMember).filter(
        ChannelMember.channel_id == visitor_channel_id,
        ChannelMember.channel_type == CHANNEL_TYPE_CUSTOMER_SERVICE,
        ChannelMember.member_type == MEMBER_TYPE_STAFF,
        ChannelMember.member_id != staff_id,  # 不移除新客服
        ChannelMember.deleted_at.is_(None),
    ).all()

    for old_member in existing_staff_members:
        old_member.deleted_at = datetime.utcnow()
        old_staff_uids_to_remove.append(f"{old_member.member_id}-staff")
        logger.info(
            f"Marked old staff {old_member.member_id} for removal from channel",
            extra={"visitor_id": str(visitor_id), "old_staff_id": str(old_member.member_id)},
        )

    # 1.2 将新客服添加到 ChannelMember 表（如果不存在）
    existing_member = db.query(ChannelMember).filter(
        ChannelMember.channel_id == visitor_channel_id,
        ChannelMember.member_id == staff_id,
        ChannelMember.deleted_at.is_(None),
    ).first()

    if not existing_member:
        channel_member = ChannelMember(
            project_id=project_id,
            channel_id=visitor_channel_id,
            channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
            member_id=staff_id,
            member_type=MEMBER_TYPE_STAFF,
        )
        db.add(channel_member)
        logger.info(
            f"Added staff {staff_id} to ChannelMember table",
            extra={"visitor_id": str(visitor_id), "staff_id": str(staff_id)},
        )

    # 1.3 获取客服显示名称（用于通知）
    if ai_disabled and send_notification:
        assigned_staff = db.query(Staff).filter(Staff.id == staff_id).first()
        staff_display_name = assigned_staff.name or assigned_staff.username if assigned_staff else str(staff_id)

    # 刷新所有数据库变更
    db.flush()

    # =====================================================================
    # 阶段2: 外部API调用（在数据库刷新之后执行）
    # 这些操作是尽力而为的，失败不会导致事务回滚
    # =====================================================================

    # 2.1 从WuKongIM移除旧客服
    for old_staff_uid in old_staff_uids_to_remove:
        try:
            await wukongim_client.remove_channel_subscribers(
                channel_id=visitor_channel_id,
                channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
                subscribers=[old_staff_uid],
            )
        except Exception as e:
            logger.warning(f"Failed to remove old staff {old_staff_uid} from WuKongIM: {e}")

    # 2.2 将新客服添加到WuKongIM频道
    try:
        await wukongim_client.add_channel_subscribers(
            channel_id=visitor_channel_id,
            channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
            subscribers=[staff_uid],
        )
        logger.info(
            f"Added staff {staff_id} to WuKongIM channel {visitor_channel_id}",
            extra={"visitor_id": str(visitor_id), "staff_id": str(staff_id)},
        )
    except Exception as e:
        logger.error(f"Failed to add staff {staff_id} to WuKongIM channel: {e}")

    # 2.3 发送客服分配系统消息（仅当AI禁用且启用通知时）
    if staff_display_name:
        try:
            await wukongim_client.send_staff_assigned_message(
                from_uid=staff_uid,
                channel_id=visitor_channel_id,
                channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
                staff_uid=staff_uid,
                staff_name=staff_display_name,
            )
            logger.info(
                f"Sent staff assigned message",
                extra={"visitor_id": str(visitor_id), "staff_id": str(staff_id), "staff_name": staff_display_name},
            )
        except Exception as e:
            logger.error(f"Failed to send staff assigned message: {e}")


# =============================================================================
# 辅助函数
# =============================================================================

def _create_assignment_history(
    db: Session,
    project_id: UUID,
    visitor_id: UUID,
    session_id: UUID,
    assigned_staff_id: Optional[UUID],
    previous_staff_id: Optional[UUID],
    assigned_by_staff_id: Optional[UUID],
    assignment_rule: Optional[VisitorAssignmentRule],
    source: AssignmentSource,
    visitor_message: Optional[str],
    notes: Optional[str],
    model_used: Optional[str],
    prompt_used: Optional[str],
    llm_response: Optional[str],
    llm_reasoning: Optional[str],
    candidate_staff_ids: List[UUID],
    candidate_scores: Optional[dict],
) -> VisitorAssignmentHistory:
    """
    创建分配历史记录。

    Returns:
        VisitorAssignmentHistory: 未提交的分配历史记录对象
    """
    assignment_history = VisitorAssignmentHistory(
        project_id=project_id,
        visitor_id=visitor_id,
        session_id=session_id,
        assigned_staff_id=assigned_staff_id,
        previous_staff_id=previous_staff_id,
        assigned_by_staff_id=assigned_by_staff_id,
        assignment_rule_id=assignment_rule.id if assignment_rule else None,
        source=source.value,
        visitor_message=visitor_message,
        notes=notes,
        model_used=model_used,
        prompt_used=prompt_used,
        llm_response=llm_response,
        reasoning=llm_reasoning,
        candidate_staff_ids=[str(sid) for sid in candidate_staff_ids] if candidate_staff_ids else None,
        candidate_scores=candidate_scores,
    )
    db.add(assignment_history)
    return assignment_history


async def _get_or_create_session(
    db: Session,
    visitor_id: UUID,
    project_id: UUID,
    session_id: Optional[UUID] = None,
    platform_id: Optional[UUID] = None,
) -> VisitorSession:
    """
    获取已存在的会话或创建新会话。
    """
    # 如果提供了 session_id，尝试获取
    if session_id:
        session = db.query(VisitorSession).filter(
            VisitorSession.id == session_id,
            VisitorSession.project_id == project_id,
        ).first()
        if session:
            return session

    # 尝试查找该访客的开放会话
    session = db.query(VisitorSession).filter(
        VisitorSession.visitor_id == visitor_id,
        VisitorSession.project_id == project_id,
        VisitorSession.status == SessionStatus.OPEN.value,
    ).order_by(VisitorSession.created_at.desc()).first()

    if session:
        return session

    # 创建新会话
    session = VisitorSession(
        project_id=project_id,
        visitor_id=visitor_id,
        platform_id=platform_id,
        status=SessionStatus.OPEN.value,
    )
    db.add(session)
    db.flush()

    logger.info(f"Created new session {session.id} for visitor {visitor_id}")
    return session


def is_within_service_hours(assignment_rule: Optional[VisitorAssignmentRule]) -> bool:
    """
    检查当前时间是否在配置的服务时间内。

    服务时间在配置的时区（默认：Asia/Shanghai）中评估。

    返回 True 的情况：
    - 未配置分配规则
    - 未配置服务时间（所有字段为 None）
    - 当前时间在服务时间内（使用配置的时区）
    """
    if not assignment_rule:
        return True

    # 获取配置的时区，默认为 Asia/Shanghai
    tz_name = assignment_rule.timezone or "Asia/Shanghai"
    try:
        tz = ZoneInfo(tz_name)
    except Exception as e:
        logger.warning(f"Invalid timezone '{tz_name}': {e}, using Asia/Shanghai")
        tz = ZoneInfo("Asia/Shanghai")

    # 在配置的时区中获取当前时间
    now = datetime.now(tz)

    # 检查星期几（配置：1=周一，7=周日；Python：0=周一，6=周日）
    if assignment_rule.service_weekdays:
        current_weekday = now.weekday() + 1  # 转换 Python 格式到配置格式
        if current_weekday not in assignment_rule.service_weekdays:
            logger.debug(f"Current weekday {current_weekday} (tz={tz_name}) not in service weekdays {assignment_rule.service_weekdays}")
            return False

    # 检查时间范围
    if assignment_rule.service_start_time and assignment_rule.service_end_time:
        try:
            start_parts = assignment_rule.service_start_time.split(":")
            end_parts = assignment_rule.service_end_time.split(":")

            start_time = time(int(start_parts[0]), int(start_parts[1]))
            end_time = time(int(end_parts[0]), int(end_parts[1]))
            current_time = now.time()

            # 处理正常情况（例如 09:00 - 18:00）
            if start_time <= end_time:
                if not (start_time <= current_time <= end_time):
                    logger.debug(f"Current time {current_time} (tz={tz_name}) not in service hours {start_time}-{end_time}")
                    return False
            else:
                # 处理跨夜情况（例如 22:00 - 06:00）
                if not (current_time >= start_time or current_time <= end_time):
                    logger.debug(f"Current time {current_time} (tz={tz_name}) not in overnight service hours {start_time}-{end_time}")
                    return False
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid service time format: {e}")
            # 如果时间格式无效，不阻塞分配
            return True

    return True


async def _get_available_staff_candidates(
    db: Session,
    project_id: UUID,
    assignment_rule: Optional[VisitorAssignmentRule] = None,
) -> List[StaffCandidate]:
    """
    获取可用客服候选人。

    过滤条件：
    - 未删除
    - 角色为普通用户（不是管理员或Agent）
    - 在服务时间内（如果配置了）
    - 未超过最大并发会话数限制（如果配置了）
    """
    # 检查是否在服务时间内
    if not is_within_service_hours(assignment_rule):
        logger.info(f"Outside service hours for project {project_id}")
        return []

    # 从规则获取最大并发会话数
    max_concurrent = None
    if assignment_rule and assignment_rule.max_concurrent_chats:
        max_concurrent = assignment_rule.max_concurrent_chats

    # 查询可用客服（仅普通用户角色，非管理员/Agent，活跃且未暂停服务）
    staff_query = db.query(Staff).filter(
        Staff.project_id == project_id,
        Staff.deleted_at.is_(None),
        Staff.is_active == True,  # noqa: E712 - SQLAlchemy 要求使用 == 比较布尔值
        Staff.service_paused == False,  # noqa: E712 - SQLAlchemy 要求使用 == 比较布尔值
    )

    available_staff = staff_query.all()

    if not available_staff:
        return []

    # 获取每个客服当前的活跃会话数
    candidates = []
    for staff in available_staff:
        active_session_count = db.query(func.count(VisitorSession.id)).filter(
            VisitorSession.staff_id == staff.id,
            VisitorSession.status == SessionStatus.OPEN.value,
        ).scalar() or 0

        # 如果达到最大容量则跳过
        if max_concurrent and active_session_count >= max_concurrent:
            logger.debug(f"Staff {staff.id} at max capacity ({active_session_count}/{max_concurrent})")
            continue

        candidates.append(StaffCandidate(
            id=staff.id,
            name=staff.name,
            nickname=staff.nickname,
            description=staff.description,
            status=staff.status,
            current_chat_count=active_session_count,
        ))

    return candidates


async def _load_balance_assign(candidates: List[StaffCandidate]) -> Optional[UUID]:
    """
    选择当前会话数最少的客服（负载均衡）。
    优先选择在线客服而非离线/忙碌客服。
    """
    if not candidates:
        return None

    # 按状态优先级（online > busy > offline）和当前会话数升序排序
    def sort_key(c: StaffCandidate) -> tuple:
        status_priority = {"online": 0, "busy": 1, "offline": 2}
        return (status_priority.get(c.status, 2), c.current_chat_count)

    sorted_candidates = sorted(candidates, key=sort_key)
    return sorted_candidates[0].id


async def _llm_assign_staff(
    db: Session,
    project_id: UUID,
    visitor: Visitor,
    visitor_message: Optional[str],
    candidates: List[StaffCandidate],
    assignment_rule: VisitorAssignmentRule,
) -> dict:
    """
    使用LLM为访客选择最合适的客服。

    Returns:
        dict: 包含 selected_staff_id, llm_response, reasoning, scores, model_used, prompt_used
    """
    result = {
        "selected_staff_id": None,
        "llm_response": None,
        "reasoning": None,
        "scores": None,
        "model_used": None,
        "prompt_used": None,
    }

    # 验证分配规则是否配置了LLM
    if not assignment_rule.ai_provider_id:
        logger.warning("LLM assignment enabled but no ai_provider_id configured, falling back to load balancing")
        result["selected_staff_id"] = await _load_balance_assign(candidates)
        result["reasoning"] = "Fallback to load balancing: no AI provider configured"
        return result

    # 构建客服信息用于提示词
    staff_info_list = []
    for i, c in enumerate(candidates, 1):
        name = c.name or c.nickname or f"Staff_{c.id}"
        desc = c.description or "No description available"
        staff_info_list.append(f"{i}. ID: {c.id}\n   Name: {name}\n   Description: {desc}\n   Current chats: {c.current_chat_count}")

    staff_info = "\n".join(staff_info_list)

    # 构建访客信息
    visitor_name = visitor.name or visitor.nickname or "Unknown"
    visitor_info = f"Name: {visitor_name}"
    if visitor_message:
        visitor_info += f"\nMessage: {visitor_message}"

    # 获取系统提示词
    system_prompt = assignment_rule.effective_prompt

    # 构建用户消息
    user_message = f"""请根据以下信息，选择最合适的客服人员来处理此访客。

## 访客信息
{visitor_info}

## 可用客服列表
{staff_info}

请返回JSON格式的结果：
{{
  "selected_staff_id": "选中的客服ID",
  "reasoning": "选择理由"
}}

只返回JSON，不要其他内容。"""

    result["prompt_used"] = f"System: {system_prompt}\n\nUser: {user_message}"
    result["model_used"] = assignment_rule.model

    try:
        from app.services.ai_client import ai_client

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        response = await ai_client.chat_completions(
            project_id=str(project_id),
            provider_id=str(assignment_rule.ai_provider_id),
            model=assignment_rule.model or "gpt-4",
            messages=messages,
            temperature=0.3,
            max_tokens=500,
        )

        # 解析响应
        if response and "choices" in response and len(response["choices"]) > 0:
            content = response["choices"][0].get("message", {}).get("content", "")
            result["llm_response"] = content

            # 尝试从响应中解析JSON
            try:
                # 处理markdown代码块
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content)
                selected_id = parsed.get("selected_staff_id")
                result["reasoning"] = parsed.get("reasoning")

                # 验证 selected_id 是否在候选人中
                candidate_ids = [str(c.id) for c in candidates]
                if selected_id and str(selected_id) in candidate_ids:
                    result["selected_staff_id"] = UUID(str(selected_id))
                    logger.info(f"LLM selected staff {selected_id}: {result['reasoning']}")
                else:
                    logger.warning(f"LLM returned invalid staff_id {selected_id}, falling back to load balancing")
                    result["selected_staff_id"] = await _load_balance_assign(candidates)
                    result["reasoning"] = f"LLM returned invalid ID, fallback to load balancing. Original: {result['reasoning']}"

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse LLM response: {e}, falling back to load balancing")
                result["selected_staff_id"] = await _load_balance_assign(candidates)
                result["reasoning"] = f"Failed to parse LLM response, fallback to load balancing"
        else:
            logger.warning("Empty LLM response, falling back to load balancing")
            result["selected_staff_id"] = await _load_balance_assign(candidates)
            result["reasoning"] = "Empty LLM response, fallback to load balancing"

    except Exception as e:
        logger.error(f"LLM assignment failed: {e}, falling back to load balancing")
        result["selected_staff_id"] = await _load_balance_assign(candidates)
        result["reasoning"] = f"LLM assignment failed: {str(e)}, fallback to load balancing"

    return result


# =============================================================================
# 高级操作函数
# =============================================================================

async def reassign_to_staff(
    db: Session,
    visitor_id: UUID,
    project_id: UUID,
    new_staff_id: UUID,
    assigned_by_staff_id: Optional[UUID] = None,
    session_id: Optional[UUID] = None,
    notes: Optional[str] = None,
) -> TransferResult:
    """
    将访客重新分配给其他客服（转接功能）。
    """
    return await transfer_to_staff(
        db=db,
        visitor_id=visitor_id,
        project_id=project_id,
        source=AssignmentSource.TRANSFER,
        target_staff_id=new_staff_id,
        assigned_by_staff_id=assigned_by_staff_id,
        session_id=session_id,
        notes=notes,
    )


async def assign_from_waiting_queue(
    db: Session,
    staff_id: UUID,
    project_id: UUID,
    queue_entry_id: Optional[UUID] = None,
) -> Optional[TransferResult]:
    """
    将等待队列中的下一个访客分配给客服。

    Args:
        db: 数据库会话
        staff_id: 要分配访客的客服ID
        project_id: 项目ID
        queue_entry_id: 指定的队列条目ID（可选，默认为队列中的下一个）

    Returns:
        TransferResult: 成功时返回转接结果，队列为空时返回 None
    """
    # 验证客服存在
    staff = db.query(Staff).filter(
        Staff.id == staff_id,
        Staff.project_id == project_id,
        Staff.deleted_at.is_(None),
    ).first()

    if not staff:
        logger.warning(f"Staff {staff_id} not found for queue assignment")
        return None

    # 获取队列条目
    if queue_entry_id:
        queue_entry = db.query(VisitorWaitingQueue).filter(
            VisitorWaitingQueue.id == queue_entry_id,
            VisitorWaitingQueue.project_id == project_id,
            VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
        ).first()
    else:
        # 获取队列中的下一个访客（按优先级降序、位置升序）
        queue_entry = db.query(VisitorWaitingQueue).filter(
            VisitorWaitingQueue.project_id == project_id,
            VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
        ).order_by(
            VisitorWaitingQueue.priority.desc(),
            VisitorWaitingQueue.position.asc(),
        ).first()

    if not queue_entry:
        logger.info(f"No visitors in waiting queue for project {project_id}")
        return None

    # 标记队列条目为已分配
    queue_entry.assign_to_staff(staff_id)
    db.flush()

    logger.info(
        f"Assigning visitor {queue_entry.visitor_id} from queue to staff {staff_id}"
    )

    # 将访客转接给客服
    result = await transfer_to_staff(
        db=db,
        visitor_id=queue_entry.visitor_id,
        project_id=project_id,
        source=AssignmentSource.RULE,
        target_staff_id=staff_id,
        session_id=queue_entry.session_id,
        visitor_message=queue_entry.visitor_message,
        notes=f"Assigned from waiting queue (position: {queue_entry.position})",
        ai_disabled=queue_entry.ai_disabled,
    )

    return result


# =============================================================================
# 队列查询函数
# =============================================================================

def get_waiting_queue_count(db: Session, project_id: UUID) -> int:
    """获取项目中等待队列中的访客数量。"""
    return db.query(VisitorWaitingQueue).filter(
        VisitorWaitingQueue.project_id == project_id,
        VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
    ).count()


def get_visitor_queue_position(
    db: Session,
    visitor_id: UUID,
    project_id: UUID
) -> Optional[int]:
    """
    获取访客在等待队列中的位置，如果不在队列中则返回 None。
    """
    queue_entry = db.query(VisitorWaitingQueue).filter(
        VisitorWaitingQueue.visitor_id == visitor_id,
        VisitorWaitingQueue.project_id == project_id,
        VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
    ).first()

    if not queue_entry:
        return None

    # 计算排在该访客前面的人数（优先级更高或位置更靠前）
    position = db.query(VisitorWaitingQueue).filter(
        VisitorWaitingQueue.project_id == project_id,
        VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
        (
            (VisitorWaitingQueue.priority > queue_entry.priority) |
            (
                (VisitorWaitingQueue.priority == queue_entry.priority) &
                (VisitorWaitingQueue.position < queue_entry.position)
            )
        )
    ).count() + 1

    return position


async def cancel_visitor_from_queue(
    db: Session,
    visitor_id: UUID,
    project_id: UUID,
) -> bool:
    """
    取消访客的等待队列条目。

    Returns:
        bool: 成功取消返回 True，不在队列中返回 False
    """
    queue_entry = db.query(VisitorWaitingQueue).filter(
        VisitorWaitingQueue.visitor_id == visitor_id,
        VisitorWaitingQueue.project_id == project_id,
        VisitorWaitingQueue.status == WaitingStatus.WAITING.value,
    ).first()

    if not queue_entry:
        return False

    queue_entry.cancel()
    db.commit()

    logger.info(f"Cancelled visitor {visitor_id} from waiting queue")
    return True