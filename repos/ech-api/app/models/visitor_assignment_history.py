"""Visitor Assignment History model for tracking LLM‑based assignment decisions."""
# 访客分配历史记录表，完整留存每一次会话分配决策，支持LLM自动分配、人工分配、规则分配、转接
# 用于问题排查、分配效果数据分析、审计回放，PostgreSQL JSONB存储半结构化上下文、候选坐席、token消耗
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, Text, func, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AssignmentSource(str, Enum):
    """Source of assignment decision."""
    LLM = "llm"         # LLM自动分配
    MANUAL = "manual"   # 人工手动分配
    RULE = "rule"       # 规则分配（轮询、负载均衡等）
    TRANSFER = "transfer"# 会话转接


class VisitorAssignmentHistory(Base):
    """History record for visitor assignments.

    This table tracks all assignment decisions made for visitors,
    including LLM reasoning and metadata for analysis.
    """

    __tablename__ = "api_visitor_assignment_history"

    # ========== 主键 ==========
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    """分配记录唯一ID"""

    # ========== 外键关联 ==========
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID",
    )
    """所属租户，租户删除级联清空全部分配历史"""

    visitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_visitors.id", ondelete="CASCADE"),
        nullable=False,
        comment="Visitor being assigned",
    )
    """被分配的访客；访客删除级联删除该访客分配记录"""

    assigned_staff_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_staff.id", ondelete="SET NULL"),
        nullable=True,
        comment="Staff member assigned to handle the visitor",
    )
    """本次分配目标坐席；坐席删除置NULL"""

    previous_staff_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_staff.id", ondelete="SET NULL"),
        nullable=True,
        comment="Previous staff member (for transfers)",
    )
    """上一任坐席，转接场景有效；普通分配为NULL"""

    assigned_by_staff_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_staff.id", ondelete="SET NULL"),
        nullable=True,
        comment="Staff who initiated the assignment (for manual assignments)",
    )
    """触发本次分配的操作人，人工分配/转接记录操作坐席；LLM自动分配为NULL"""

    assignment_rule_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_visitor_assignment_rules.id", ondelete="SET NULL"),
        nullable=True,
        comment="Assignment rule used (for LLM assignments)",
    )
    """使用的分配规则配置ID，LLM/规则分配场景填写"""

    session_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("api_visitor_sessions.id", ondelete="SET NULL"),
        nullable=True,
        comment="Associated visitor session",
    )
    """绑定访客业务会话，一次会话可产生多条分配历史（多次转接、重分配）"""

    # ========== 分配基础信息 ==========
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AssignmentSource.LLM.value,
        comment="Source of assignment: llm, manual, rule, transfer",
    )
    """分配来源，枚举 AssignmentSource；区分四种分配路径"""

    # ========== LLM分配专属字段 ==========
    model_used: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="LLM model used for this assignment",
    )
    """本次分配调用的大模型名称"""

    prompt_used: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Prompt sent to LLM",
    )
    """发给LLM的完整Prompt，用于复现调试"""

    llm_response: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Full LLM response",
    )
    """LLM原始输出完整文本"""

    reasoning: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="LLM reasoning for the assignment decision",
    )
    """LLM输出的思考推理过程，解释为什么选该坐席"""

    # ========== 分配时刻访客上下文快照 ==========
    visitor_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Visitor's message/question at assignment time",
    )
    """触发分配时访客最新消息文本"""

    visitor_context: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional visitor context (intent, sentiment, etc.)",
    )
    """访客上下文JSON：意图、情绪标签、历史标签等快照"""

    # ========== 候选坐席信息 ==========
    candidate_staff_ids: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
        comment="List of staff IDs considered for assignment",
    )
    """本次分配纳入评估的候选坐席ID列表"""

    candidate_scores: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Scores/rankings for each candidate",
    )
    """各候选坐席打分、排序结果，key=staff_id，value=分数/评估维度"""

    # ========== LLM性能指标 ==========
    response_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="LLM response time in milliseconds",
    )
    """LLM调用耗时(毫秒)，监控分配接口性能"""

    token_usage: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Token usage statistics",
    )
    """token消耗：input/output/total，用于统计成本"""

    # ========== 备注 ==========
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Additional notes or comments",
    )
    """人工备注，异常分配记录问题说明"""

    # ========== 时间戳 ==========
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Assignment timestamp",
    )
    """分配发生时间；本表只追加写入，无updated_at，历史不可修改"""

    # ========== ORM关系 ==========
    project: Mapped["Project"] = relationship(
        "Project",
        lazy="select",
    )
    visitor: Mapped["Visitor"] = relationship(
        "Visitor",
        lazy="select",
    )
    assigned_staff: Mapped[Optional["Staff"]] = relationship(
        "Staff",
        foreign_keys=[assigned_staff_id],
        lazy="select",
    )
    previous_staff: Mapped[Optional["Staff"]] = relationship(
        "Staff",
        foreign_keys=[previous_staff_id],
        lazy="select",
    )
    assigned_by_staff: Mapped[Optional["Staff"]] = relationship(
        "Staff",
        foreign_keys=[assigned_by_staff_id],
        lazy="select",
    )
    assignment_rule: Mapped[Optional["VisitorAssignmentRule"]] = relationship(
        "VisitorAssignmentRule",
        lazy="select",
    )
    session: Mapped[Optional["VisitorSession"]] = relationship(
        "VisitorSession",
        back_populates="assignment_histories",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<VisitorAssignmentHistory(id={self.id}, visitor_id={self.visitor_id}, "
            f"assigned_staff_id={self.assigned_staff_id}, source={self.source})>"
        )