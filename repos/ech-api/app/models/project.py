"""Project model."""
# 项目模型：多租户隔离的顶层租户模型，一个Project代表一个租户/客户
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

# SQLAlchemy ORM 基础模型类，所有数据库表继承 Base
from app.core.database import Base


class Project(Base):
    """Project model for multi‑tenant isolation.
    多租户顶层模型，整个系统所有业务数据都归属某一个Project（租户）。
    采用软删除：删除不会物理DELETE行，仅填充deleted_at时间戳。
    """

    # 映射数据库真实表名
    __tablename__ = "api_projects"

    # ========== 主键字段 ==========
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    """主键UUID，新建记录时自动生成uuid4，全局唯一租户ID"""

    # ========== 基础业务字段 ==========
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Project name"
    )
    """租户项目名称，不可为空"""

    api_key: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="API key for authentication"
    )
    """租户对外调用API的凭证，全局唯一，用来鉴权区分不同客户"""

    # ========== 时间戳字段 ==========
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )
    """记录创建时间；func.now() 使用数据库服务端时间，而非应用本地时间"""

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )
    """记录更新时间；记录发生update时数据库自动刷新为当前时间"""

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Soft deletion timestamp"
    )
    """软删除时间戳；不为NULL代表租户已被删除；NULL代表有效可用"""

    # ========== ORM关系映射：一对多 / 一对一 ==========
    """
    relationship 说明：
    - back_populates：与子模型的 project 属性双向互关联
    - cascade="all, delete‑orphan"：级联规则
        all：增、改操作级联到子对象
        delete‑orphan：Project删除/解除关联，子表记录同步删除
    - lazy="select"：访问属性时，额外单独SQL查询加载子数据（默认策略）
    """

    # 一个项目下拥有多个渠道 Platform
    platforms: Mapped[List["Platform"]] = relationship(
        "Platform",
        back_populates="project",
        cascade="all, delete‑orphan",
        lazy="select"
    )

    # 项目下的内部工作人员
    staff: Mapped[List["Staff"]] = relationship(
        "Staff",
        back_populates="project",
        cascade="all, delete‑orphan",
        lazy="select"
    )

    # 访客（咨询用户）
    visitors: Mapped[List["Visitor"]] = relationship(
        "Visitor",
        back_populates="project",
        cascade="all, delete‑orphan",
        lazy="select"
    )

    # 标签
    tags: Mapped[List["Tag"]] = relationship(
        "Tag",
        back_populates="project",
        cascade="all, delete‑orphan",
        lazy="select"
    )

    # 访客‑标签中间关联表
    visitor_tags: Mapped[List["VisitorTag"]] = relationship(
        "VisitorTag",
        back_populates="project",
        cascade="all, delete‑orphan",
        lazy="select"
    )

    # AI提供商配置
    ai_providers: Mapped[List["AIProvider"]] = relationship(
        "AIProvider",
        back_populates="project",
        cascade="all, delete‑orphan",
        lazy="select"
    )

    # uselist=False：一对一关系，一个Project对应一条ProjectAIConfig记录，不是列表
    ai_config: Mapped[Optional["ProjectAIConfig"]] = relationship(
        "ProjectAIConfig",
        back_populates="project",
        uselist=False,
        cascade="all, delete‑orphan",
        lazy="select",
    )

    # 租户初始化引导进度，一对一
    onboarding_progress: Mapped[Optional["ProjectOnboardingProgress"]] = relationship(
        "ProjectOnboardingProgress",
        back_populates="project",
        uselist=False,
        cascade="all, delete‑orphan",
        lazy="select",
    )

    # 访客分配规则配置，一对一
    visitor_assignment_rule: Mapped[Optional["VisitorAssignmentRule"]] = relationship(
        "VisitorAssignmentRule",
        back_populates="project",
        uselist=False,
        cascade="all, delete‑orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        """String representation of the project.
        对象打印输出，调试日志用，便于看对象内容
        """
        return f"<Project(id={self.id}, name='{self.name}')>"

    @property
    def is_deleted(self) -> bool:
        """Check if the project is soft deleted.
        只读属性，业务层直接判断 project.is_deleted，不用每次写 deleted_at is not None
        """
        return self.deleted_at is not None