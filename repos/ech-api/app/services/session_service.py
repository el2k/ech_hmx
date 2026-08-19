# =============================================================================
# 模块：会话服务 (Session service)
# =============================================================================
# 该模块提供了访客会话管理的核心功能，主要包括：
# 1. 关闭访客会话 - 完整的会话关闭流程
# 2. 与会话关闭相关的联动操作（状态更新、频道清理、队列触发等）
# =============================================================================

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import Staff, VisitorSession, SessionStatus, VisitorServiceStatus, ChannelMember
from app.services.wukongim_client import wukongim_client
from app.services.queue_trigger_service import trigger_queue_for_staff
from app.utils.encoding import build_visitor_channel_id
from app.utils.const import CHANNEL_TYPE_CUSTOMER_SERVICE

logger = get_logger("services.session")


# =============================================================================
# 核心函数：关闭访客会话
# =============================================================================

async def close_visitor_session(
    db: Session,
    session: VisitorSession,
    closed_by_staff: Optional[Staff] = None,
    send_notification: bool = True,
    auto_commit: bool = True,
    reason: Optional[str] = None,
) -> VisitorSession:
    """
    关闭访客会话的公用方法。

    这是会话关闭的统一入口，执行以下完整流程：
    1. 从 WuKongIM 获取频道最后一条消息
    2. 关闭会话（更新状态、关闭时间、计算时长）
    3. 更新访客服务状态为 CLOSED
    4. 从 ChannelMember 表和 WuKongIM 频道移除客服
    5. 发送会话关闭系统通知
    6. 删除客服端的会话记录
    7. 触发队列处理（客服释放了一个并发槽位）

    设计考量：
    - 所有外部 API 调用（WuKongIM）都是异步且非阻塞的
    - 外部 API 失败不会导致整体操作失败（容错设计）
    - 数据库操作和外部 API 调用分离，减少事务持有时间
    - 支持由客服主动关闭和系统自动关闭两种场景

    Args:
        db: 数据库会话
        session: 要关闭的会话对象（需要已加载 visitor 关系）
        closed_by_staff: 关闭会话的客服（可选，用于发送通知和日志）
        send_notification: 是否发送系统通知消息
        auto_commit: 是否自动提交事务
        reason: 关闭原因（可选，用于日志记录）

    Returns:
        关闭后的会话对象

    Raises:
        ValueError: 如果会话已经关闭
    """
    # =====================================================================
    # 前置检查：验证会话状态
    # =====================================================================
    # 防止重复关闭已关闭的会话
    if session.status == SessionStatus.CLOSED.value:
        raise ValueError("Session is already closed")

    close_reason = reason or ("by staff" if closed_by_staff else "unknown")

    logger.info(
        f"Closing session {session.id}",
        extra={
            "session_id": str(session.id),
            "visitor_id": str(session.visitor_id),
            "closed_by": str(closed_by_staff.id) if closed_by_staff else None,
            "reason": close_reason,
        }
    )

    # =====================================================================
    # 步骤1: 从 WuKongIM 获取频道最后一条消息
    # =====================================================================
    # 目的：记录会话的最后一条消息序列号和时间，用于后续数据统计和审计
    # 容错：如果获取失败，只记录警告日志，不影响会话关闭流程
    channel_id = build_visitor_channel_id(session.visitor_id)
    try:
        last_message = await wukongim_client.get_channel_last_message(
            channel_id=channel_id,
            channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
        )

        if last_message:
            # 更新会话的最后消息信息
            session.last_message_seq = last_message.message_seq
            if last_message.timestamp:
                # WuKongIM 的时间戳单位是秒，需要转换为 datetime
                session.last_message_at = datetime.fromtimestamp(last_message.timestamp)
            logger.debug(f"Updated session with last message info: seq={session.last_message_seq}")
    except Exception as e:
        # 获取最后消息失败不影响会话关闭
        logger.warning(f"Failed to get channel last message: {e}")

    # =====================================================================
    # 步骤2: 关闭会话
    # =====================================================================
    # session.close() 方法会：
    # - 将状态设置为 CLOSED
    # - 设置 closed_at 为当前时间
    # - 计算会话持续时间 duration_seconds
    session.close()  # This sets status=closed, closed_at, and calculates duration
    session.updated_at = datetime.utcnow()

    # =====================================================================
    # 步骤3: 更新访客服务状态
    # =====================================================================
    # 访客的服务状态从 ACTIVE（服务中）变为 CLOSED（已关闭）
    # 这样访客可以重新发起新的会话
    visitor = session.visitor
    if visitor:
        visitor.service_status = VisitorServiceStatus.CLOSED.value
        visitor.updated_at = datetime.utcnow()

    # =====================================================================
    # 步骤4: 提交数据库变更（或刷新）
    # =====================================================================
    if auto_commit:
        db.commit()
        db.refresh(session)
    else:
        db.flush()

    logger.info(
        f"Session {session.id} closed successfully",
        extra={
            "session_id": str(session.id),
            "duration_seconds": session.duration_seconds,
            "closed_at": str(session.closed_at),
            "reason": close_reason,
        }
    )

    # =====================================================================
    # 步骤5: 从 WuKongIM 频道和 ChannelMember 表移除客服
    # =====================================================================
    # 目的：客服不再接收该访客频道的消息，权限清理
    # 分为两步：
    #   a) 数据库软删除（ChannelMember 表）
    #   b) WuKongIM 移除订阅者
    # 数据库操作先执行，外部 API 调用在后且不阻塞
    if session.staff_id:
        # 5a: 从 ChannelMember 表移除（软删除）
        channel_member = db.query(ChannelMember).filter(
            ChannelMember.channel_id == channel_id,
            ChannelMember.member_id == session.staff_id,
            ChannelMember.member_type == "staff",
            ChannelMember.deleted_at.is_(None),
        ).first()

        if channel_member:
            channel_member.deleted_at = datetime.utcnow()
            db.flush()
            logger.info(f"Removed staff {session.staff_id} from ChannelMember table for channel {channel_id}")

        # 5b: 从 WuKongIM 频道移除订阅者（异步，不阻塞）
        try:
            staff_uid = f"{session.staff_id}-staff"
            await wukongim_client.remove_channel_subscribers(
                channel_id=channel_id,
                channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
                subscribers=[staff_uid],
            )
            logger.info(f"Removed staff {session.staff_id} from WuKongIM channel {channel_id}")
        except Exception as e:
            # 移除失败不影响会话关闭（权限清理是尽力而为的）
            logger.warning(f"Failed to remove staff from WuKongIM channel: {e}")

    # =====================================================================
    # 步骤6: 发送会话关闭系统消息
    # =====================================================================
    # 目的：通知访客会话已关闭，提升用户体验
    # 消息会显示在访客端的聊天界面中
    if send_notification:
        try:
            staff_uid = None
            staff_name = None

            if closed_by_staff:
                staff_uid = f"{closed_by_staff.id}-staff"
                staff_name = closed_by_staff.name or closed_by_staff.nickname or closed_by_staff.username

            await wukongim_client.send_session_closed_message(
                from_uid=staff_uid or "system",
                channel_id=channel_id,
                channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
                staff_uid=staff_uid,
                staff_name=staff_name,
            )
            logger.info(f"Sent session closed message for session {session.id}")
        except Exception as e:
            # 通知发送失败不影响会话关闭
            logger.error(f"Failed to send session closed message: {e}")

    # =====================================================================
    # 步骤7: 删除客服端的会话记录
    # =====================================================================
    # 目的：清理客服的会话列表，避免客服看到已结束的会话
    # 这是一个用户体验优化，不影响核心功能
    if session.staff_id:
        try:
            staff_uid = f"{session.staff_id}-staff"
            await wukongim_client.delete_conversation(
                uid=staff_uid,
                channel_id=channel_id,
                channel_type=CHANNEL_TYPE_CUSTOMER_SERVICE,
            )
            logger.info(f"Deleted conversation for staff {session.staff_id}, session {session.id}")
        except Exception as e:
            # 删除失败不影响会话关闭
            logger.warning(f"Failed to delete conversation from WuKongIM: {e}")

    # =====================================================================
    # 步骤8: 触发队列处理
    # =====================================================================
    # 关键步骤：客服关闭会话后释放了一个并发槽位
    # 触发队列处理，让等待中的访客有机会被分配给这个客服
    # 这是事件驱动队列处理的核心入口
    if session.staff_id and session.project_id:
        try:
            await trigger_queue_for_staff(session.staff_id, session.project_id)
        except Exception as e:
            # 队列触发失败只记录错误，不影响会话关闭
            # 后续会有 fallback 任务兜底处理
            logger.error(f"Failed to trigger queue processing: {e}")

    return session