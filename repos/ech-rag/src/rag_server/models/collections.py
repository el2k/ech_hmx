"""
Collection model for organizing documents.
"""

import enum
from typing import List, Optional

from sqlalchemy import ARRAY, Enum, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin
# CollectionType 指定集合的类型或来源
class CollectionType(str, enum.Enum):
    """
    Enum representing the type/source of a collection.

    - file: Collection created from file uploads
    - website: Collection created from website crawling
    - qa: Collection created from question-answer pairs
    """
    file = "file"
    website = "website"
    qa = "qa"

class Collection(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "rag_collections"
    project_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        doc="Associated project ID (logical reference to API service)",
    )
    collection_type: Mapped[CollectionType] = mapped_column(
        Enum(CollectionType, name="collection_type_enum", create_type=True),
        nullable=False,
        default=CollectionType.file,
        server_default="file",
        doc="Type/source of the collection"
    )
    crawl_config: Mapped[Optional[dict]] = mapped_column(
            JSONB,
            nullable=True,
            doc="Crawl configuration for website collections. Contains settings like start_url, "
                "max_pages, max_depth, include/exclude patterns, timeouts, and rendering options.",
    )
     # Collection information
    display_name: Mapped[str] = mapped_column(
            String(255),
            nullable=False,
            doc="Human-readable collection name",
    )
    description: Mapped[Optional[str]] = mapped_column(
            Text,
            nullable=True,
            doc="Collection description",
        )
    # 这里的 collection_metadata 字段用于存储集合的元数据，例如嵌入模型、分块大小等信息。它是一个可选的 JSONB 类型字段，可以存储任意结构化数据。
    collection_metadata: Mapped[Optional[dict]] = mapped_column(
            JSONB,
            nullable=True,
            doc="Collection metadata (embedding model, chunk size, etc.)",
        )
    tags: Mapped[Optional[List[str]]] = mapped_column(
        # ARRAY(String) 类型用于存储字符串数组，这里用于存储集合的标签信息。标签可以用于对集合进行分类和过滤。
            ARRAY(String),
            nullable=True,
            doc="Collection tags for categorization and filtering",
        )   
    # relationships指定了集合与其他实体之间的关系，例如文件、文档和问答对。通过这些关系，可以方便地访问和操作与集合相关的实体。
    documents: Mapped[List["FileDocument"]] = relationship(
            "FileDocument",
            back_populates="collection",
            cascade="all, delete-orphan",
            doc="Documents in this collection",
        )
    
    qa_pairs: Mapped[List["QAPair"]] = relationship(
            "QAPair",
            back_populates="collection",
            cascade="all, delete-orphan",
            doc="QA pairs in this collection (for qa type collections)",
        )
    
        # Indexes
    __table_args__ = (
            Index("idx_rag_collections_project_id", "project_id"),
            Index("idx_rag_collections_collection_type", "collection_type"),
            Index("idx_rag_collections_display_name", "display_name"),
            Index("idx_rag_collections_created_at", "created_at"),
            Index("idx_rag_collections_deleted_at", "deleted_at"),
            Index("idx_rag_collections_project_display_name", "project_id", "display_name"),
            Index("idx_rag_collections_tags", "tags", postgresql_using="gin"),
        )
    # __repr__ 方法提供了集合对象的字符串表示，便于调试和日志记录。它显示了集合的 ID、显示名称和关联的项目 ID。
    def __repr__(self) -> str:
        """String representation of the collection."""
        return f"<Collection(id={self.id}, display_name='{self.display_name}', project_id={self.project_id})>"
    # property 指定了一个只读属性 document_count，它返回集合中包含的文档数量。如果集合中没有文档，则返回 0。这个属性提供了一个方便的方式来获取集合的文档数量，而无需直接访问 documents 列表。
    @property
    def document_count(self) -> int:
        """Get the number of documents in this collection."""
        return len(self.documents) if self.documents else 0
    # get_metadata_value 方法用于获取集合元数据中的特定键的值。如果集合没有元数据或指定的键不存在，则返回默认值。这个方法提供了一种方便的方式来访问集合的元数据，而无需直接操作 collection_metadata 字段。
    def get_metadata_value(self, key: str, default=None):
        """
        Get a specific metadata value.

        Args:
            key: Metadata key to retrieve
            default: Default value if key not found

        Returns:
            Metadata value or default
        """
        if not self.collection_metadata:
            return default
        return self.collection_metadata.get(key, default)
    
    def set_metadata_value(self, key: str, value) -> None:
        """
        Set a specific metadata value.

        Args:
            key: Metadata key to set
            value: Value to set
        """
        if self.collection_metadata is None:
            self.collection_metadata = {}
        self.collection_metadata[key] = value
    
    def update_metadata(self, updates: dict) -> None:
        """
        Update multiple metadata values.

        Args:
            updates: Dictionary of key-value pairs to update
        """
        if self.collection_metadata is None:
            self.collection_metadata = {}
        self.collection_metadata.update(updates)
    
    
