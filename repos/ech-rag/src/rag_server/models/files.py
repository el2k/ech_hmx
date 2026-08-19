"""
File model for uploaded files.
"""

from typing import List, Optional

from sqlalchemy import ARRAY, BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class File(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """
    File model representing uploaded files for RAG processing.
    
    This model stores metadata about uploaded files and tracks their
    processing status through the document extraction pipeline.
    """

    __tablename__ = "rag_files"

    # Foreign keys
    project_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        doc="Associated project ID (logical reference to API service)",
    )
    # collection_id 这个字段是可选的，允许文件不属于任何集合。它使用外键引用 rag_collections 表的 id 字段，并在删除集合时将其设置为 NULL。
    collection_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rag_collections.id", ondelete="SET NULL"),
        nullable=True,
        doc="Associated collection ID",
    )

    # File information
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Original filename when uploaded",
    )

    file_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        doc="File size in bytes",
    )
    # content_type 字段存储文件的 MIME 类型，例如 "application/pdf" 或 "image/png"。它是一个字符串，最大长度为 100 个字符，并且不能为空。
    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="MIME type of the file",
    )

    # Storage information
    storage_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        # local: 存储在本地文件系统中
        # s3: 存储在 Amazon S3 中
        # gcs: 存储在 Google Cloud Storage 中
        # azure: 存储在 Microsoft Azure Blob Storage 中
        doc="Storage provider (local, s3, gcs, azure)",
    )

    storage_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Path to file in storage system",
    )
    # storage_metadata 字段存储与文件存储相关的元数据，例如存储桶名称、区域等。它是一个可选的 JSONB 字段，可以为空。
    storage_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Storage-specific metadata (bucket, region, etc.)",
    )

    # Processing information
    status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="pending",
        doc="Processing status (pending, processing, chunking_documents, generating_embeddings, completed, failed, archived)",
        # 状态: pending: 文件已上传，但尚未开始处理
        # processing: 文件正在处理中
        # chunking_documents: 文件正在被分块为文档
        # generating_embeddings: 文件的文档正在生成嵌入向量
        # completed: 文件处理完成，文档和嵌入向量已生成
        # failed: 文件处理失败
        # archived: 文件已归档，不再参与处理
    )
    # document_count 字段存储从文件中生成的文档块的数量。它是一个整数，默认值为 0，并且不能为空。
    document_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of document chunks generated from this file",
    )

    total_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total number of tokens across all document chunks",
    )

    # Content metadata
    language: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        doc="Detected or specified language (ISO 639-1 code)",
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        doc="Optional file description",
    )
    # tags 字段存储文件的标签，用于分类和过滤。它是一个可选的字符串数组，可以为空。
    tags: Mapped[Optional[List[str]]] = mapped_column(
        ARRAY(String),
        nullable=True,
        doc="File tags for categorization and filtering",
    )

    # User information
    uploaded_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="User who uploaded the file",
    )

    # Relationships
    # collection 字段表示文件所属的集合。它是一个可选的关系，指向 Collection 模型，并在 Collection 模型中通过 back_populates 关联到 files 字段。
    collection: Mapped[Optional["Collection"]] = relationship(
        "Collection",
        back_populates="files",
        doc="Associated collection",
    )
    # documents 字段表示从文件中生成的文档块。它是一个关系，指向 FileDocument 模型，并在 FileDocument 模型中通过 back_populates 关联到 file 字段。它还指定了级联删除策略，当文件被删除时，相关的文档块也会被删除。
    documents: Mapped[List["FileDocument"]] = relationship(
        "FileDocument",
        back_populates="file",
        cascade="all, delete-orphan",
        doc="Document chunks generated from this file",
    )

    # Indexes
    __table_args__ = (
        Index("idx_rag_files_project_id", "project_id"),
        Index("idx_rag_files_collection_id", "collection_id"),
        Index("idx_rag_files_status", "status"),
        Index("idx_rag_files_content_type", "content_type"),
        Index("idx_rag_files_storage_provider", "storage_provider"),
        Index("idx_rag_files_uploaded_by", "uploaded_by"),
        Index("idx_rag_files_language", "language"),
        Index("idx_rag_files_created_at", "created_at"),
        Index("idx_rag_files_project_status", "project_id", "status"),
        Index("idx_rag_files_project_content_type", "project_id", "content_type"),
        Index("idx_rag_files_project_uploaded_by", "project_id", "uploaded_by"),
        Index("idx_rag_files_deleted_at", "deleted_at"),
        Index("idx_rag_files_tags", "tags", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        """String representation of the file."""
        return f"<File(id={self.id}, filename='{self.original_filename}', status='{self.status}')>"

    @property
    def is_processing(self) -> bool:
        """Check if the file is currently being processed."""
        return self.status == "processing"

    @property
    def is_completed(self) -> bool:
        """Check if the file processing is completed."""
        return self.status == "completed"

    @property
    def is_failed(self) -> bool:
        """Check if the file processing failed."""
        return self.status == "failed"

    def update_status(self, status: str) -> None:
        """
        Update the file processing status.
        
        Args:
            status: New status value
        """
        valid_statuses = {"pending", "processing", "chunking_documents", "generating_embeddings", "completed", "failed", "archived"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid status: {status}. Must be one of {valid_statuses}")
        self.status = status

    def has_tag(self, tag: str) -> bool:
        """
        Check if the file has a specific tag.

        Args:
            tag: Tag to check for

        Returns:
            True if tag exists, False otherwise
        """
        if not self.tags:
            return False
        return tag in self.tags

    def add_tag(self, tag: str) -> None:
        """
        Add a tag to the file.

        Args:
            tag: Tag to add
        """
        if self.tags is None:
            self.tags = []
        if tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag: str) -> None:
        """
        Remove a tag from the file.

        Args:
            tag: Tag to remove
        """
        if self.tags and tag in self.tags:
            self.tags.remove(tag)
