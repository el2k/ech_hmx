"""Project onboarding progress tracking model."""
# 租户初始化引导进度表，与 Project 一对一
# 记录租户新建之后，系统引导配置AI、模型、知识库、Agent、首次对话的每一步完成状态
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ProjectOnboardingProgress(Base):
    """Tracks onboarding progress for a project (one‑to‑one with Project).

    Stores completion status for each onboarding step:
    - Step 1: Set up AI Provider        配置AI服务商
    - Step 2: Set default models       设置默认模型
    - Step 3: Create RAG Collection    创建RAG向量知识库集合
    - Step 4: Create Agent with knowledge base  创建绑定知识库的智能Agent
    - Step 5: Start first chat         发起第一次对话
    """

    __tablename__ = "api_project_onboarding_progress"

    # ========== 主键 ==========
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    """独立UUID主键"""

    # ========== 一对一外键 ==========
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID (unique)",
    )
    """关联租户Project；租户删除，级联删除该引导进度记录；联合唯一约束保证一个租户仅有一条记录"""

    # ========== 分步完成标记 ==========
    step_1_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether AI provider setup is completed",
    )
    """步骤1：AI服务商配置完成"""

    step_2_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether default models are configured",
    )
    """步骤2：默认大模型配置完成"""

    step_3_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether RAG collection is created",
    )
    """步骤3：RAG向量库集合已创建"""

    step_4_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether agent with knowledge base is created",
    )
    """步骤4：绑定知识库的Agent智能体已创建"""

    step_5_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether first chat is started",
    )
    """步骤5：完成第一次对话交互"""

    # ========== 整体完成状态 ==========
    is_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="Whether all onboarding steps are completed or skipped",
    )
    """
    总开关：初始化引导是否全部完成/手动跳过。
    ⚠️注意：业务逻辑，不自动由5个step字段计算；允许用户手动跳过全部引导直接置True。
    """

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Timestamp when onboarding was completed or skipped",
    )
    """引导完成/被跳过的时间点，is_completed=True时填充"""

    # ========== 时间戳 & 软删除 ==========
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())
    """记录创建时间，租户初始化时生成该行"""

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=func.now(), onupdate=func.now()
    )
    """每一步状态变更自动更新时间"""

    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    """软删除时间戳，本表极少做软删除，一般随project直接级联删除"""

    # ========== ORM关系 ==========
    project: Mapped["Project"] = relationship(
        "Project", back_populates="onboarding_progress", lazy="select"
    )
    """反向关联Project租户；Project模型中配置 onboarding_progress，uselist=False实现一对一"""

    # ========== 表约束 ==========
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_onboarding_project_id"),
    )
    """唯一约束：一个project_id只能拥有一条onboarding进度记录，防止重复生成"""

    def __repr__(self) -> str:  # pragma: no cover - debug
        return f"<ProjectOnboardingProgress(project_id={self.project_id}, is_completed={self.is_completed})>"