"""
Document model for processed document chunks.
"""

from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Import pgvector with fallback for development
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    # Fallback for development without pgvector installed
    from sqlalchemy import ARRAY, Float
    Vector = lambda dim: ARRAY(Float)

from .base import Base, TimestampMixin, UUIDMixin


class FileDocument(Base, UUIDMixin, TimestampMixin):
    """
    Document model representing processed document chunks for RAG operations.
    
    This model stores individual document chunks extracted from files,
    along with their vector embeddings and metadata for semantic search.
    """
    
    staticmethod
    table_name = "rag_file_documents"

    __tablename__ = table_name

    # Foreign keys
    project_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        doc="Associated project ID for multi-tenant isolation",
    )

    file_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rag_files.id", ondelete="SET NULL"),
        nullable=True,
        doc="Associated file ID (nullable for QA pairs)",
    )

    collection_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rag_collections.id", ondelete="SET NULL"),
        nullable=True,
        doc="Associated collection ID",
    )



    # Document content
    document_title: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        doc="Document title or heading",
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Document content text for RAG processing",
    )
    # content_tsv 指的是 PostgreSQL 中的全文搜索向量字段，用于支持混合搜索功能。它存储了文档内容的向量化表示，以便在进行语义搜索时能够快速匹配相关内容。
    content_tsv: Mapped[Optional[str]] = mapped_column(
        TSVECTOR,
        nullable=True,
        doc="PostgreSQL full-text search vector for hybrid search capabilities",
    )

    content_length: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        doc="Length of content in characters",
    )
    # token_count 指的是文档内容中的令牌数量。令牌通常是指文本被分割成的最小单位，例如单词或子词。在自然语言处理和语义搜索中，令牌数量可以用于衡量文本的复杂性和长度。
    # 这里的“令牌”就是文本经过分词器（Tokenizer）切分后得到的最小文本片段，token_count 就是用来统计这段内容里到底有多少个这样的片段。
    token_count: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Number of tokens in the content",
    )

    # Document structure
    # chunk_index 指的是文档块在整个文档中的索引位置。它用于标识每个文档块在原始文档中的顺序，以便在处理和检索时能够保持正确的顺序。
    chunk_index: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Index of this chunk within the document",
    )

    section_title: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        doc="Section or chapter title",
    )

    page_number: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Page number in original document",
    )

    # Content classification
    content_type: Mapped[str] = mapped_column(
        String(50),
        nullable=True, 
        default="paragraph",
        doc="Type of content (paragraph, heading, table, list, code, image, metadata)",
        # paragraph: 普通文本段落
        # heading: 标题或章节标题
        # table: 表格内容
        # list: 列表项
        # code: 代码片段
        # image: 图像描述或图像相关文本
        # metadata: 元数据或附加信息
    )

    language: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        doc="Document language (ISO 639-1 code)",
    )

    confidence_score: Mapped[Optional[float]] = mapped_column(
        # Numeric(3, 2) 表示一个数值类型，最多有 3 位数字，其中 2 位是小数位。这意味着该字段可以存储从 0.00 到 9.99 的数值。
        Numeric(3, 2),
        nullable=True,
        doc="Confidence score for content extraction (0.0-1.0)",
    )

    # Metadata and tags
    tags: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        doc="Document tags and metadata for RAG categorization",
    )

    # Vector embedding information
    # embedding_model 字段存储用于生成嵌入向量的模型名称，例如 "text-embedding-ada-002"。它是一个可选的字符串字段，可以为空。
    embedding_model: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        doc="Model used to generate embeddings",
    )
    # embedding_dimensions 字段存储嵌入向量的维度数量，例如 1536。它是一个可选的整数字段，可以为空。
    embedding_dimensions: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        doc="Dimensions of the embedding vector",
    )

    # Vector embedding (stored in PostgreSQL with pgvector)
    # embedding 字段存储文档的嵌入向量，用于语义搜索。它使用 pgvector 扩展在 PostgreSQL 中存储向量数据。默认情况下，嵌入向量的维度为 1536，这是 OpenAI 的默认嵌入维度。
    embedding: Mapped[Optional[list]] = mapped_column(
        Vector(1536),  # Default OpenAI embedding dimensions
        nullable=True,
        doc="Vector embedding for semantic search",
    )

    # Relationships
    file: Mapped[Optional["File"]] = relationship(
        "File",
        back_populates="documents",
        doc="Associated file (optional for QA pairs)",
    )

    collection: Mapped[Optional["Collection"]] = relationship(
        "Collection",
        back_populates="documents",
        doc="Associated collection",
    )

    # Indexes
    __table_args__ = (
        Index("idx_rag_file_documents_file_id", "file_id"),
        Index("idx_rag_file_documents_collection_id", "collection_id"),
        Index("idx_rag_file_documents_content_type", "content_type"),
        Index("idx_rag_file_documents_language", "language"),
        Index("idx_rag_file_documents_chunk_index", "chunk_index"),
        Index("idx_rag_file_documents_page_number", "page_number"),
        Index("idx_rag_file_documents_token_count", "token_count"),
        Index("idx_rag_file_documents_confidence_score", "confidence_score"),
        Index("idx_rag_file_documents_embedding_model", "embedding_model"),
        Index("idx_rag_file_documents_created_at", "created_at"),
        Index("idx_rag_file_documents_content_tsv", "content_tsv", postgresql_using="gin"),
        Index("idx_rag_file_documents_file_chunk", "file_id", "chunk_index"),
    )

    def __repr__(self) -> str:
        """String representation of the document."""
        return f"<FileDocument(id={self.id}, content_type='{self.content_type}', file_id={self.file_id})>"

    @property
    def has_embedding(self) -> bool:
        """Check if the document has an embedding vector."""
        return self.embedding is not None

    # content_preview 方法用于获取文档内容的预览。它接受一个可选的长度参数，默认值为 100。如果文档内容的长度小于或等于指定长度，则返回完整内容；否则，返回截断后的内容，并在末尾添加省略号。
    @property
    def content_preview(self, length: int = 100) -> str:
        """
        Get a preview of the document content.
        
        Args:
            length: Maximum length of the preview
            
        Returns:
            Truncated content preview
        """
        if len(self.content) <= length:
            return self.content
        return self.content[:length] + "..."
    # get_tag_value 方法用于获取文档的特定标签值。它接受一个标签键和一个可选的默认值作为参数。如果文档的标签字典为空或不包含指定键，则返回默认值；否则，返回对应的标签值。
    def get_tag_value(self, key: str, default=None):
        """
        Get a specific tag value.
        
        Args:
            key: Tag key to retrieve
            default: Default value if key not found
            
        Returns:
            Tag value or default
        """
        if not self.tags:
            return default
        return self.tags.get(key, default)

    def set_tag_value(self, key: str, value) -> None:
        """
        Set a specific tag value.
        
        Args:
            key: Tag key to set
            value: Value to set
        """
        if self.tags is None:
            self.tags = {}
        self.tags[key] = value

    # update_embedding_info 方法用于更新文档的嵌入相关信息。它接受一个模型名称和向量维度作为参数，并将这些值分别存储在 embedding_model 和 embedding_dimensions 字段中。
    def update_embedding_info(self, model: str, dimensions: int) -> None:
        """
        Update embedding-related information.

        Args:
            model: Embedding model name
            dimensions: Vector dimensions
        """
        self.embedding_model = model
        self.embedding_dimensions = dimensions
