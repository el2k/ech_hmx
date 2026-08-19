"""Agent models for AI agent management."""

import uuid
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, ForeignKey, JSON, String, Text, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, foreign

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.collection import AgentCollection
    from app.models.workflow import AgentWorkflow
    from app.models.project import Project
    from app.models.llm_provider import LLMProvider
    from app.models.tool import Tool


class Agent(BaseModel):
    """
    Agent 模型 - 用于 AI 代理定义。
    Agents表示具有自己配置、指令和工具绑定的独立 AI 助手。
    Agent model for AI agent definitions.

    Agents represent individual AI assistants with their own configuration,
    instructions, and tool bindings.
    """

    __tablename__ = "ai_agents"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Associated project ID (logical reference to API service)",
    )

    llm_provider_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_llm_providers.id", ondelete="SET NULL"),
        nullable=True,
        comment="Associated LLM provider (credentials) ID",
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Agent name",
    )

    instruction: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Agent system instruction",
    )

    model: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        comment='LLM model with provider prefix (format: "provider:model_name")',
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this is the default agent for the project",
    )

    config: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="Agent configuration (temperature, max_tokens, markdown, add_datetime_to_context, etc.)",
    )

    is_remote_store_agent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this is a remote agent from store",
    )

    remote_agent_url: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="URL of the remote AgentOS server",
    )

    store_agent_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Agent ID in the remote store",
    )

    agent_category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="normal",
        comment="Agent category: normal or computer_use",
    )
    # bound_device_id 是用于设备控制 MCP 连接的绑定设备 ID，确保代理与特定设备关联。
    bound_device_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Bound device ID for device control MCP connection",
    )
    # skills_enabled 是一个布尔值，指示是否为该代理启用技能发现功能，允许代理探索和使用可用的技能。
    skills_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
        comment="Whether to enable skill discovery for this agent",
    )

    # Relationships
    project: Mapped["Project"] = relationship(
        "Project",
        primaryjoin="foreign(Agent.project_id) == Project.id",
        back_populates="agents",
        lazy="selectin",
    )

    llm_provider: Mapped[Optional["LLMProvider"]] = relationship(
        "LLMProvider",
        lazy="selectin",
    )

    tools: Mapped[List["Tool"]] = relationship(
        "Tool",
        secondary="ai_agent_tool_associations",
        primaryjoin="Agent.id == foreign(AgentToolAssociation.agent_id)",
        secondaryjoin="Tool.id == foreign(AgentToolAssociation.tool_id)",
        back_populates="agents",
        lazy="selectin",
    )

    collections: Mapped[List["AgentCollection"]] = relationship(
        "AgentCollection",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    workflows: Mapped[List["AgentWorkflow"]] = relationship(
        "AgentWorkflow",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index(
            "uq_ai_agents_default_per_project_active",
            "project_id",
            unique=True,
            postgresql_where=sa.text("is_default = true AND deleted_at IS NULL"),
            sqlite_where=sa.text("is_default = 1 AND deleted_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        """String representation of the agent."""
        return f"<Agent(id={self.id}, name='{self.name}', project_id={self.project_id})>"

    @property
    def provider(self) -> str:
        """Extract provider from model string."""
        if ":" in self.model:
            return self.model.split(":", 1)[0]
        return "unknown"

    @property
    def model_name(self) -> str:
        """Extract model name from model string."""
        if ":" in self.model:
            return self.model.split(":", 1)[1]
        return self.model

    @property
    def collection_ids(self) -> List[str]:
        """Get the collection IDs from agent collections."""
        return [agent_collection.collection_id for agent_collection in self.collections]

    @property
    def workflow_ids(self) -> List[str]:
        """Get the workflow IDs from agent workflows."""
        return [agent_workflow.workflow_id for agent_workflow in self.workflows]


class AgentToolAssociation(BaseModel):
    """
    连接代理和工具的关联实体，具有每个代理的设置。
    存储每个代理的启用状态、权限和给定工具的配置覆盖。
    Association entity between agents and tools with per-agent settings.

    Stores per-agent enablement, permissions, and configuration overrides
    for a given Tool.
    """

    __tablename__ = "ai_agent_tool_associations"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Associated agent ID",
    )

    tool_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Associated tool ID",
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether tool is enabled for this agent",
    )

    permissions: Mapped[Optional[List[str]]] = mapped_column(
        JSON,
        nullable=True,
        comment="Tool permissions array",
    )

    config: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="Agent-specific tool configuration overrides",
    )


    __table_args__ = (
        Index("idx_agent_tool_assoc_agent_id", "agent_id"),
        Index("idx_agent_tool_assoc_tool_id", "tool_id"),
    )

    def __repr__(self) -> str:  # pragma: no cover - convenience
        return f"<AgentToolAssociation(agent_id={self.agent_id}, tool_id={self.tool_id})>"
