"""Visitor Waiting Queue model for managing visitors waiting for staff assignment."""
# 访客排队队列模型，统一管理等待坐席人工接待的访客；数据库实现的持久化排队，替代内存队列
# 支持多来源入队、四级紧急度优先级、状态流转、内置业务工具方法；可定时任务轮询消费队列
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.visitor import Visitor
    from app.models.visitor_session import VisitorSession
    from app.models.staff import Staff


class WaitingStatus(str, Enum):
    """Waiting queue status enumeration."""
    WAITING = "waiting"      # 访客正在排队等待
    ASSIGNED = "assigned"    # 已分配坐席，出队
    CANCELLED = "cancelled" # 访客主动取消/离开，出队
    EXPIRED = "expired"     # 等待超时过期，出队


class QueueSource(str, Enum):
    """Queue entry source enumeration."""
    AI_REQUEST = "ai_request"     # AI Agent 请求人工介入
    VISITOR_REQUEST = "visitor"  # 访客主动点转人工
    TRANSFER = "transfer"        # 坐席转接过来
    SYSTEM = "system"            # 系统自动触发（超时强制转人工）
    NO_STAFF = "no_staff"        # 无空闲坐席，自动进入排队


class QueueUrgency(str, Enum):
    """Queue urgency level enumeration."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# 紧急度映射数值优先级：数值越大优先级越高
URGENCY_PRIORITY_MAP = {
    QueueUrgency.LOW.value: 0,
    QueueUrgency.NORMAL.value: 1,
    QueueUrgency.HIGH.value: 2,
    QueueUrgency.URGENT.value: 3,
}


class VisitorWaitingQueue(Base):
    """Visitor waiting queue for managing visitors awaiting staff assignment.

    This is the unified queue for all human service requests, including:
    - AI agent requests for manual service
    - Visitor explicit requests for human service
    - Automatic queuing when no staff is available
    - Staff transfers
    """

    __tablename__ = "api_visitor_waiting_queue"

    # ========== 主键 ==========
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    """排队记录唯一ID，每一次入队生成一条记录，一次会话可多次入队产生多条记录"""

    # ========== 外键关联 ==========
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID",
    )
    """租户ID，租户删除级联清空排队记录"""

    visitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_visitors.id", ondelete="CASCADE"),
        nullable=False,
        comment="Visitor waiting in queue",
    )
    """排队的访客"""

    session_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_visitor_sessions.id", ondelete="SET NULL"),
        nullable=True,
        comment="Associated visitor session",
    )
    """关联访客会话；会话删除置NULL，保留排队历史"""

    assigned_staff_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_staff.id", ondelete="SET NULL"),
        nullable=True,
        comment="Staff member who picked this visitor from queue",
    )
    """从队列取出后分配的坐席；未分配为NULL"""

    # ========== 入队来源 & 紧急度 ==========
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=QueueSource.NO_STAFF.value,
        comment="Queue entry source: ai_request, visitor, transfer, system, no_staff",
    )
    """入队来源，枚举QueueSource，区分5种转人工场景"""

    urgency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=QueueUrgency.NORMAL.value,
        comment="Urgency level: low, normal, high, urgent",
    )
    """业务紧急等级，前端/业务逻辑设置"""

    # ========== 队列排序字段 ==========
    position: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Queue position (lower = higher priority)",
    )
    """排队序号，数值越小越靠前；⚠️数据库不会自动维护position，业务代码/消费逻辑维护"""

    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Priority level (higher = more urgent), derived from urgency",
    )
    """优先级数值，由urgency转换而来；数值越大优先级越高；高优先级优先被消费"""

    # ========== 状态 ==========
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=WaitingStatus.WAITING.value,
        comment="Queue status: waiting, assigned, cancelled, expired",
    )
    """队列状态枚举WaitingStatus；只有WAITING状态属于有效排队，其余均为已出队终态"""

    # ========== AI开关标记 ==========
    ai_disabled: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        default=None,
        comment="Whether AI responses should be disabled (None=keep current, True=disable, False=enable)",
    )
    """进入人工排队后，是否关闭AI自动回复；None不改动原有设置"""

    # ========== 入队上下文快照 ==========
    visitor_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Message that triggered the transfer request",
    )
    """触发转人工的访客消息快照"""

    reason: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Reason for entering queue (e.g., 'No available staff', 'AI requested')",
    )
    """入队简短原因"""

    channel_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Associated communication channel identifier",
    )
    """WuKongIM频道ID"""

    channel_type: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Associated communication channel type code",
    )
    """IM频道类型"""

    extra_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Additional contextual metadata",
    )
    """扩展JSON上下文，存放访客标签、情绪等附加信息"""

    # ========== 分配重试 & 过期控制 ==========
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Timestamp of the last assignment attempt",
    )
    """上一次尝试分配坐席的时间，用于避免高频重试"""

    expired_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="When this entry should expire if not assigned",
    )
    """排队超时截止时间，到达时间标记expired状态"""

    # ========== 完整时间轴 ==========
    entered_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="When visitor entered the queue",
    )
    """入队时间"""

    assigned_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="When visitor was assigned to a staff",
    )
    """分配坐席时间，仅ASSIGNED状态有值"""

    exited_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="When visitor exited the queue (assigned, cancelled, or expired)",
    )
    """出队时间：分配/取消/过期都会填充"""

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Record creation timestamp",
    )
    """记录创建时间，基本等价entered_at"""

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp",
    )
    """记录更新时间，状态流转自动更新"""

    # ========== ORM关系 ==========
    project: Mapped["Project"] = relationship(
        "Project",
        lazy="select",
    )
    visitor: Mapped["Visitor"] = relationship(
        "Visitor",
        lazy="select",
    )
    session: Mapped[Optional["VisitorSession"]] = relationship(
        "VisitorSession",
        lazy="select",
    )
    assigned_staff: Mapped[Optional["Staff"]] = relationship(
        "Staff",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<VisitorWaitingQueue(id={self.id}, visitor_id={self.visitor_id}, "
            f"source={self.source}, status={self.status}, position={self.position})>"
        )

    # ========== 业务属性（计算属性，不写库） ==========
    @property
    def is_waiting(self) -> bool:
        """Check if visitor is still waiting."""
        return self.status == WaitingStatus.WAITING.value

    @property
    def is_expired(self) -> bool:
        """Check if this entry has passed its expiration time."""
        if not self.expired_at:
            return False
        return datetime.utcnow() > self.expired_at

    @property
    def wait_duration_seconds(self) -> Optional[int]:
        """Calculate how long the visitor has been waiting.
        已出队：计算总排队时长；仍在排队：计算已等待秒数
        """
        if self.exited_at:
            return int((self.exited_at - self.entered_at).total_seconds())
        return int((datetime.utcnow() - self.entered_at).total_seconds())

    def needs_fallback_processing(self, fallback_delay_seconds: int = 120) -> bool:
        """Check if this entry should be processed by the fallback processor.

        Returns True if:
        - Status is WAITING
        - Not expired
        - Either never attempted, or last attempt was more than fallback_delay_seconds ago
        """
        if self.status != WaitingStatus.WAITING.value:
            return False
        if self.is_expired:
            return False
        if self.last_attempt_at is None:
            return True
        cutoff = datetime.utcnow() - timedelta(seconds=fallback_delay_seconds)
        return self.last_attempt_at < cutoff

    # ========== 状态流转方法（内存修改，需db.commit生效） ==========
    def assign_to_staff(self, staff_id: UUID) -> None:
        """Mark this queue entry as assigned to a staff member. 分配坐席，出队"""
        now = datetime.utcnow()
        self.status = WaitingStatus.ASSIGNED.value
        self.assigned_staff_id = staff_id
        self.assigned_at = now
        self.exited_at = now
        self.updated_at = now

    def cancel(self) -> None:
        """Mark this queue entry as cancelled. 访客取消排队"""
        now = datetime.utcnow()
        self.status = WaitingStatus.CANCELLED.value
        self.exited_at = now
        self.updated_at = now

    def expire(self) -> None:
        """Mark this queue entry as expired. 排队超时过期"""
        now = datetime.utcnow()
        self.status = WaitingStatus.EXPIRED.value
        self.exited_at = now
        self.updated_at = now

    def record_attempt(self) -> None:
        """Record an assignment attempt. 记录一次分配尝试，用于限流重试"""
        now = datetime.utcnow()
        self.last_attempt_at = now
        self.updated_at = now

    @staticmethod
    def urgency_to_priority(urgency: str) -> int:
        """Convert urgency level to priority number. 紧急度转优先级数值"""
        return URGENCY_PRIORITY_MAP.get(urgency, 1)