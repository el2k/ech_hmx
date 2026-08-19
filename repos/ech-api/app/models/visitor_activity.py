"""Visitor activity model."""
# 访客行为动态模型：访客时间线事件，记录访客发生的各类行为，形成时间轴流水日志
# 一对多：一个Visitor可以有多条VisitorActivity，每次行为新增一条记录，不更新旧记录
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VisitorActivity(Base):
    """Timeline entry representing a visitor activity.
    访客时间线条目，记录访客发生的各类行为事件。
    属于流水日志表：发生一次行为就INSERT一行，历史记录不做修改；支持软删除。
    前端可基于本表渲染访客完整行为时间轴。
    """

    __tablename__ = "api_visitor_activities"

    # 主键UUID，新建自动生成
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # 租户ID，多租户隔离
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID for multi‑tenant isolation"
    )
    """
    所属租户；
    ondelete="CASCADE"：数据库外键级联，租户删除，该租户全部访客行为记录物理删除。
    """

    # 关联访客ID
    visitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_visitors.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated visitor ID"
    )
    """
    外键关联访客主表；
    ondelete="CASCADE"：访客删除，数据库自动删除该访客全部行为流水。
    """

    activity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Categorised type of activity"
    )
    """
    行为分类类型，短字符串，用于归类过滤。
    示例：session_start会话开始、message_send发送消息、file_upload上传文件、agent_assign坐席分配。
    """

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Short title or headline for the activity"
    )
    """行为简短标题，前端时间线直接展示的摘要标题"""

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Detailed description of the activity"
    )
    """行为详细描述，Text大文本类型，可以存放较长文本内容，允许为空"""

    context: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Arbitrary structured context for the activity"
    )
    """
    行为附带结构化上下文，JSONB。
    可存放该事件相关扩展数据，例如会话ID、消息ID、操作参数，不固定schema。
    """

    duration_seconds: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Duration associated with the activity, in seconds"
    )
    """行为持续时长，单位秒；无时长的事件可以为NULL，例如发送消息事件"""

    occurred_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="When the activity occurred"
    )
    """
    **事件实际发生时间**。
    注意区分 created_at：occurred_at是行为发生时刻；created_at是这条数据库记录入库时刻。
    例如异步延迟写入日志时，两者会存在时间差。
    """

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Record creation timestamp"
    )
    """数据库记录入库时间"""

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Record update timestamp"
    )
    """记录更新时间，流水日志正常业务不会修改，软删除时会更新"""

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Soft deletion timestamp"
    )
    """软删除时间；不为NULL代表这条行为记录被逻辑删除，不物理删除行"""

    # ORM双向关系：访客一对多行为流水
    visitor: Mapped["Visitor"] = relationship(
        "Visitor",
        back_populates="activities",
        lazy="select"
    )
    """
    通过 activity.visitor 获取访客对象。
    Visitor模型侧定义 activities = relationship(back_populates="visitor")，一对多返回列表。
    lazy="select"：访问才额外发出SQL。
    """

    def __repr__(self) -> str:
        """调试日志打印"""
        return f"<VisitorActivity(id={self.id}, visitor_id={self.visitor_id}, type='{self.activity_type}')>"