"""Add permissions tables for RBAC.

Revision ID: 0005_add_permissions_tables
Revises: 0004_fix_staff_role_constraint
Create Date: 2024-12-07

This migration creates three tables for the RBAC permission system:
1. api_permissions - Permission definitions (resource:action)
2. api_role_permissions - Global role permissions (inherited by all projects)
3. api_project_role_permissions - Project-specific additional permissions

Permission model: Merge mode
- Final permissions = Global permissions + Project-specific permissions
- Projects can only ADD permissions, not disable global ones
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0005_add_permissions_tables"
down_revision: Union[str, None] = "0004_fix_staff_role_constraint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create permissions tables."""
    
    # 1. Create api_permissions table - Permission definitions
    op.create_table(
        "api_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "resource",
            sa.String(50),
            nullable=False,
            comment="Resource name: staff, ai_agents, rag_collections, etc.",
        ),
        sa.Column(
            "action",
            sa.String(20),
            nullable=False,
            comment="Action: create, read, update, delete, list",
        ),
        sa.Column(
            "description",
            sa.String(255),
            nullable=True,
            comment="Human-readable description of the permission",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            comment="Creation timestamp",
        ),
        sa.UniqueConstraint("resource", "action", name="uq_permission_resource_action"),
    )

    # 2. Create api_role_permissions table - Global role permissions (no project_id)
    # These permissions are inherited by ALL projects
    op.create_table(
        "api_role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            comment="Role name: user, admin, agent",
        ),
        sa.Column(
            "permission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_permissions.id", ondelete="CASCADE"),
            nullable=False,
            comment="Associated permission ID",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            comment="Creation timestamp",
        ),
        # Unique per role + permission (global, no project)
        sa.UniqueConstraint(
            "role", "permission_id",
            name="uq_role_permission",
        ),
    )

    # 3. Create api_project_role_permissions table - Project-specific additional permissions
    # These are MERGED with global permissions
    op.create_table(
        "api_project_role_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "role",
            sa.String(20),
            nullable=False,
            comment="Role name: user, admin, agent",
        ),
        sa.Column(
            "permission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_permissions.id", ondelete="CASCADE"),
            nullable=False,
            comment="Associated permission ID",
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_projects.id", ondelete="CASCADE"),
            nullable=False,
            comment="Associated project ID for project-specific permissions",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            comment="Creation timestamp",
        ),
        # Unique per role + permission + project
        sa.UniqueConstraint(
            "role", "permission_id", "project_id",
            name="uq_project_role_permission",
        ),
    )

    # Create indexes for better query performance
    op.create_index(
        "ix_api_permissions_resource",
        "api_permissions",
        ["resource"],
    )
    op.create_index(
        "ix_api_role_permissions_role",
        "api_role_permissions",
        ["role"],
    )
    op.create_index(
        "ix_api_project_role_permissions_role",
        "api_project_role_permissions",
        ["role"],
    )
    op.create_index(
        "ix_api_project_role_permissions_project_id",
        "api_project_role_permissions",
        ["project_id"],
    )


def downgrade() -> None:
    """Drop permissions tables."""
    # Drop indexes
    op.drop_index("ix_api_project_role_permissions_project_id", "api_project_role_permissions")
    op.drop_index("ix_api_project_role_permissions_role", "api_project_role_permissions")
    op.drop_index("ix_api_role_permissions_role", "api_role_permissions")
    op.drop_index("ix_api_permissions_resource", "api_permissions")

    # Drop tables (order matters due to foreign keys)
    op.drop_table("api_project_role_permissions")
    op.drop_table("api_role_permissions")
    op.drop_table("api_permissions")
