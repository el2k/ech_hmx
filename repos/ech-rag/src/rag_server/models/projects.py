"""
Project model for local project management.
"""

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

# 本地项目管理的 Project 模型，用于维护项目范围内的操作信息。
class Project(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """
    Project model for local project management.

    This table maintains project information for project-scoped operations
    in the RAG service.
    """

    __tablename__ = "rag_projects"

    # Core project information
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Project name",
    )
    
    api_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        doc="API key for project authentication",
    )
    


    # Indexes
    __table_args__ = (
        Index("idx_rag_projects_api_key", "api_key"),
        Index("idx_rag_projects_deleted_at", "deleted_at"),
    )

    def __repr__(self) -> str:
        """String representation of the project."""
        return f"<Project(id={self.id}, name='{self.name}', api_key='{self.api_key[:8]}...')>"


