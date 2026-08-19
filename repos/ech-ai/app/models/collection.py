"""Collection models for knowledge base management."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.project import Project

# 项目级别的知识集合元数据模型，用于管理与项目相关的知识集合信息。
class Collection(BaseModel):
    """Project-level knowledge collection metadata."""

    __tablename__ = "ai_collections"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Associated project ID",
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Collection display name",
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional collection description",
    )

    external_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        comment="External RAG service collection identifier",
    )

    project: Mapped["Project"] = relationship(
        "Project",
        primaryjoin="foreign(Collection.project_id) == Project.id",
        back_populates="collections",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Collection(id={self.id}, project_id={self.project_id}, name='{self.name}')>"


class AgentCollection(BaseModel):
    """
    多对多关系模型，表示代理和集合之间的关系。
    表达了哪些集合可以被代理访问，用于知识检索操作。集合数据是通过存储的 collection_id 从外部 RAG 服务中检索的。
    Many-to-many relationship between agents and collections.

    Represents which collections an agent has access to for
    knowledge retrieval operations. Collection data is retrieved
    from external RAG service using the stored collection_id.
    """

    __tablename__ = "ai_agent_collections"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated agent ID",
    )

    collection_id: Mapped[str] = mapped_column(
        String(36),  # UUID string length
        nullable=False,
        comment="Collection ID (UUID string) - references external RAG service",
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this collection is enabled for the agent",
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(
        "Agent",
        back_populates="collections",
        lazy="selectin",
    )
    # __repr__ 方法提供了代理集合关系的字符串表示形式，显示了代理 ID、集合 ID 和启用状态。
    def __repr__(self) -> str:
        """String representation of the agent collection relationship."""
        return f"<AgentCollection(agent_id={self.agent_id}, collection_id='{self.collection_id}', enabled={self.enabled})>"
