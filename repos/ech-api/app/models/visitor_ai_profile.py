"""Visitor AI profile model."""
# 访客AI画像模型：保存聚合后的访客人格画像数据
# 和 VisitorAIInsight 区分：Insight 是单轮会话即时洞察；Profile 是多轮会话累积聚合出来的长期画像
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, UniqueConstraint, func
# PostgreSQL JSONB类型，支持索引、JSON内部查询
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VisitorAIProfile(Base):
    """Aggregated AI persona data for a visitor.
    访客聚合AI人格画像，沉淀多轮对话累积得到的访客标签、结构化画像摘要。
    每个访客最多拥有1条画像记录；随着访客不断对话，持续更新本条记录，不新增行。
    """

    __tablename__ = "api_visitor_ai_profiles"

    # 主键UUID，新建自动生成
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # 租户ID，多租户隔离；数据库级联删除：租户删除，画像记录随之删除
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID for multi‑tenant isolation"
    )

    # 关联访客ID；数据库级联删除：访客删除，画像记录随之删除
    visitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_visitors.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated visitor ID"
    )

    persona_tags: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="List of AI generated persona tags"
    )
    """
    AI生成的访客人格标签数组，JSONB存储字符串列表，默认空列表[]。
    示例：["价格敏感","意向高","喜欢线上沟通","对售后担忧"]
    由历史多轮对话聚合提炼，用于客服侧展示、AI提示词注入。
    """

    summary: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Structured summary data for AI persona"
    )
    """
    结构化画像摘要，JSONB字典，允许为NULL。
    存放复杂的画像结构化信息，例如：消费偏好、忌讳点、背景信息、关注点等。
    字段结构不固定，不需要变更数据表即可扩展内容。
    """

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )
    """记录创建时间，取数据库服务端时间"""

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )
    """记录更新时间，数据修改时数据库自动刷新"""

    # ORM双向关系，关联Visitor访客模型
    visitor: Mapped["Visitor"] = relationship(
        "Visitor",
        back_populates="ai_profile",
        lazy="select"
    )
    """
    通过 profile.visitor 获取所属访客对象。
    Visitor模型侧需要定义：ai_profile = relationship(back_populates="visitor", uselist=False)，实现一对一。
    lazy="select"：访问属性才触发额外SQL查询。
    """

    __table_args__ = (
        # 数据库唯一约束：一个访客只能有一条AI画像记录，防止业务逻辑bug产生多条
        UniqueConstraint("visitor_id", name="uk_api_visitor_ai_profile_visitor"),
    )

    def __repr__(self) -> str:
        """调试打印、日志输出"""
        return f"<VisitorAIProfile(visitor_id={self.visitor_id})>"