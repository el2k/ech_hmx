"""Permission models for RBAC."""
# RBAC权限模型：全局角色权限 + 租户扩展角色权限
# 权限编码格式 resource:action；最终权限 = 全局RolePermission ∪ 租户ProjectRolePermission
# 租户只能追加权限，不能屏蔽全局预置权限
from datetime import datetime
from typing import Optional, List
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# 权限表
class Permission(Base):
    """Permission definition model.

    Defines available permissions in the system using resource:action format.
    Examples: staff:create, staff:read, ai_agents:update
    """

    __tablename__ = "api_permissions"

    # ========== 主键 ==========
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    """权限定义唯一UUID"""

    # ========== 权限定义 resource:action ==========
    resource: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Resource name: staff, ai_agents, rag_collections, etc."
    )
    """资源对象，如 staff、ai_agents、rag_collections"""

    action: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Action: create, read, update, delete, list"
    )
    """动作：create / read / update / delete / list"""

    description: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Human‑readable description of the permission"
    )
    """权限可读描述，用于前端展示"""

    # ========== 时间戳 ==========
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )
    """权限定义创建时间，一般是系统初始化migrate预置"""

    # ========== ORM关系 ==========
    role_permissions: Mapped[List["RolePermission"]] = relationship(
        "RolePermission",
        back_populates="permission",
        lazy="select"
    )
    """反向：该权限被哪些【全局角色】引用"""

    project_role_permissions: Mapped[List["ProjectRolePermission"]] = relationship(
        "ProjectRolePermission",
        back_populates="permission",
        lazy="select"
    )
    """反向：该权限被哪些【租户级角色】引用"""

    # ========== 约束 ==========
    __table_args__ = (
        UniqueConstraint("resource", "action", name="uq_permission_resource_action"),
    )
    """数据库唯一约束：同一个resource+action只能定义一条权限，避免重复权限定义"""

    def __repr__(self) -> str:
        """String representation of the permission."""
        return f"<Permission(id={self.id}, resource='{self.resource}', action='{self.action}')>"

    @property
    def code(self) -> str:
        """Get permission code in resource:action format."""
        return f"{self.resource}:{self.action}"
    """快捷属性，拼接成标准权限字符串，例：staff:create"""


class RolePermission(Base):
    """Global Role‑Permission association model.

    Defines default permissions for roles across ALL projects.
    When a new permission is added, only this table needs to be updated.
    All projects automatically inherit these permissions.

    Final project permissions = RolePermission (global) + ProjectRolePermission (project‑specific)
    """

    __tablename__ = "api_role_permissions"

    # ========== 主键 ==========
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    """全局角色‑权限关联主键"""

    # ========== 全局角色权限（无project_id） ==========
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Role name: user, admin, agent"
    )
    """角色标识：user / admin / agent，全局角色，作用于所有租户"""

    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_permissions.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated permission ID"
    )
    """关联Permission权限定义；权限删除级联删除本条关联"""

    # ========== 时间戳 ==========
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )

    # ========== ORM关系 ==========
    permission: Mapped["Permission"] = relationship(
        "Permission",
        back_populates="role_permissions",
        lazy="select"
    )
    """正向关联Permission权限对象"""

    # ========== 约束 ==========
    __table_args__ = (
        UniqueConstraint(
            "role", "permission_id",
            name="uq_role_permission"
        ),
    )
    """全局：同一个角色不能重复绑定同一个权限"""

    def __repr__(self) -> str:
        """String representation of the global role permission."""
        return f"<RolePermission(id={self.id}, role='{self.role}', permission_id={self.permission_id})>"


class ProjectRolePermission(Base):
    """Project‑specific Role‑Permission association model.

    Defines additional permissions for roles within a specific project.
    These permissions are MERGED with global RolePermission.
    Projects can only ADD permissions, not disable global ones.

    Final project permissions = RolePermission (global) + ProjectRolePermission (project‑specific)
    """

    __tablename__ = "api_project_role_permissions"

    # ========== 主键 ==========
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    """租户级角色‑权限关联主键"""

    # ========== 租户角色权限 ==========
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Role name: user, admin, agent"
    )
    """角色标识，和全局role语义一致"""

    permission_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_permissions.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated permission ID"
    )
    """关联Permission权限定义"""

    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID for project‑specific permissions"
    )
    """所属租户；租户删除级联清空该租户全部扩展权限"""

    # ========== 时间戳 ==========
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )

    # ========== ORM关系 ==========
    permission: Mapped["Permission"] = relationship(
        "Permission",
        back_populates="project_role_permissions",
        lazy="select"
    )
    """关联权限定义"""

    project: Mapped["Project"] = relationship(
        "Project",
        lazy="select"
    )
    """关联租户Project"""

    # ========== 约束 ==========
    __table_args__ = (
        UniqueConstraint(
            "role", "permission_id", "project_id",
            name="uq_project_role_permission"
        ),
    )
    """租户内约束：同一个租户+角色，不能重复添加同一个扩展权限"""

    def __repr__(self) -> str:
        """String representation of the project role permission."""
        return f"<ProjectRolePermission(id={self.id}, role='{self.role}', project_id={self.project_id})>"