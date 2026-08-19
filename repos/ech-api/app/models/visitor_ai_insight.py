"""Visitor AI insight model."""
# 访客AI洞察模型：存储AI分析访客对话后产出的情感、满意度、意图、摘要等分析结果
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, func
# PostgreSQL专属JSONB类型，支持索引、查询JSON内部字段
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

# ORM基类，所有数据表模型继承自Base
from app.core.database import Base


class VisitorAIInsight(Base):
    """AI derived insight metrics for a visitor.
    由AI分析会话生成的访客洞察指标，每个访客最多拥有1条洞察记录。
    当访客产生新对话时，AI分析完成后更新本条记录，不新增多行。
    """

    __tablename__ = "api_visitor_ai_insights"

    # 主键，UUID自动生成
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # 多租户外键，关联租户项目表 api_projects
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID for multi‑tenant isolation"
    )
    """
    租户ID，用于多租户隔离；
    ondelete="CASCADE"：如果所属Project租户被删除，这条洞察记录跟随数据库层面物理删除。
    """

    # 访客外键，关联访客主表 api_visitors
    visitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_visitors.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated visitor ID"
    )
    """
    关联访客ID；
    ondelete="CASCADE"：访客记录删除，本条AI洞察数据库级联删除。
    """

    satisfaction_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Latest satisfaction score on a 0‑5 scale (0=unknown)"
    )
    """访客满意度分数，取值范围0‑5；0代表未知；可为NULL"""

    emotion_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Latest emotion score on a 0‑5 scale (0=unknown)"
    )
    """访客情绪分数，0‑5，数值越高情绪越积极；0代表未知"""

    intent: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Visitor intent classification (e.g., purchase, inquiry, complaint, support)"
    )
    """访客意图分类，AI输出短标签：purchase购买 / inquiry咨询 / complaint投诉 / support求助"""

    insight_summary: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Brief natural language summary of the insight"
    )
    """AI生成的自然语言简短摘要，总结该访客整体情况，最多500字符"""

    insight_metadata: Mapped[dict] = mapped_column(
        "metadata",   # 数据库真实列名叫 metadata，ORM属性名叫 insight_metadata，做名字隔离
        JSONB,
        nullable=False,
        default=dict,
        comment="Additional metadata for the AI insight"
    )
    """
    AI洞察扩展元数据，PostgreSQL JSONB类型。
    default=dict：新建记录默认是空字典 {}。
    可以存放模型版本、置信度、原始prompt、标签列表等灵活的KV数据，不需要频繁改表结构。
    JSONB支持建立GIN索引，可以直接SQL查询json内部字段。
    """

    # 记录创建时间，使用数据库服务端时间
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )

    # 记录更新时间，记录变更时数据库自动刷新
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )

    # ORM双向关系：反向关联Visitor访客模型
    visitor: Mapped["Visitor"] = relationship(
        "Visitor",
        back_populates="ai_insight",
        lazy="select"
    )
    """
    访问 visitor_ai_insight.visitor 拿到所属访客对象；
    Visitor模型一侧要有 ai_insight = relationship(back_populates="visitor", uselist=False)，一对一。
    lazy="select"：访问该属性才会额外发出SQL查询访客。
    """

    # 表级约束
    __table_args__ = (
        # 唯一约束：一个visitor_id只能出现一次，保证每个访客最多一条AI洞察
        UniqueConstraint("visitor_id", name="uk_api_visitor_ai_insight_visitor"),
    )

    def __repr__(self) -> str:
        """调试打印输出，日志使用"""
        return f"<VisitorAIInsight(visitor_id={self.visitor_id})>"