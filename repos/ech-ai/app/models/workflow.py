"""Workflow models for orchestration management."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.agent import Agent


class AgentWorkflow(BaseModel):
    """
    多对多关系 - 代理和工作流之间的关系。
    表达了代理可以访问或触发哪些工作流。
    工作流数据是从外部 tgo-workflow 服务中检索的，使用存储的 workflow_id。
    Many-to-many relationship between agents and workflows.

    Represents which workflows an agent has access to or can trigger.
    Workflow data is retrieved from external tgo-workflow service
    using the stored workflow_id.
    """

    __tablename__ = "ai_agent_workflows"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated agent ID",
    )

    workflow_id: Mapped[str] = mapped_column(
        String(36),  # UUID string length
        nullable=False,
        comment="Workflow ID (UUID string) - references external workflow service",
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this workflow is enabled for the agent",
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(
        "Agent",
        back_populates="workflows",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        """String representation of the agent workflow relationship."""
        return f"<AgentWorkflow(agent_id={self.agent_id}, workflow_id='{self.workflow_id}', enabled={self.enabled})>"
