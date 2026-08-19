"""
Project-level embedding configuration model.

Table: rag_embedding_configs
"""

import uuid
from typing import Optional

from sqlalchemy import Boolean, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class EmbeddingConfig(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Embedding configuration stored per project (project_id is not FK).

    Notes:
    - For phase 1, dimensions are enforced to 1536 at the API layer for
      compatibility with existing vector tables.
    - Only one active configuration per project is allowed (unique partial index).
    """

    __tablename__ = "rag_embedding_configs"

    # Upstream project identifier (NOT a foreign key on purpose)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        doc="Upstream project ID; not constrained as a foreign key",
    )

    # Provider and model info
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    # Operational parameters
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False, default=1536)
    # batch_size 是每次批量处理的向量数量，默认值为 10
    batch_size: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    # Provider credentials/endpoint
    api_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    base_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Activation flag
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        # Fast lookups
        # Index 第一个参数是索引的名称，第二个参数是要索引的列名
        Index("ix_rag_embedding_configs_project_id", "project_id"),
        Index("ix_rag_embedding_configs_is_active", "is_active"),
        # Ensure only one active config per project (partial unique index)
        Index(
            "uq_rag_embedding_configs_project_active",
            "project_id",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<EmbeddingConfig(id={self.id}, project_id={self.project_id}, "
            f"provider={self.provider}, model={self.model}, active={self.is_active})>"
        )

