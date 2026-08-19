"""
Document-related Pydantic schemas.
"""
# 文件相关的 Pydantic 模型定义，包括创建文档请求、文档响应和文档列表响应等。
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

class DocumentCreateRequest(BaseModel):
    """Schema for creating documents directly in a collection."""

    document_title: Optional[str] = Field(
        None,
        max_length=500,
        description="Document title or heading",
        examples=["Installation Overview"]
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Document content text for RAG processing",
        examples=["This section provides an overview of the installation process for the software..."]
    )
    content_type: str = Field(
        default="paragraph",
        description="Type of content",
        examples=["paragraph", "heading", "table", "list", "code", "image", "metadata"]
    )
    section_title: Optional[str] = Field(
        None,
        max_length=255,
        description="Section or chapter title",
        examples=["Installation Guide"]
    )
    page_number: Optional[int] = Field(
        None,
        ge=1,
        description="Page number in original document",
        examples=[1]
    )
    chunk_index: Optional[int] = Field(
        None,
        ge=0,
        description="Index of this chunk within the document",
        examples=[0]
    )
    language: Optional[str] = Field(
        None,
        max_length=10,
        description="Document language (ISO 639-1)",
        examples=["en", "es", "fr"]
    )
    tags: Optional[Dict[str, Any]] = Field(
        None,
        description="Document tags and metadata for RAG categorization",
        examples=[
            {
                "section": "installation",
                "difficulty": "beginner"
            }
        ]
    )
    
class DocumentResponse(BaseModel):
    """Schema for document API responses."""
    
    id: UUID = Field(
        ...,
        description="Document unique identifier"
    )
    file_id: UUID = Field(
        ...,
        description="Associated file ID"
    )
    collection_id: Optional[UUID] = Field(
        None,
        description="Associated collection ID",
        examples=["coll_123e4567-e89b-12d3-a456-426614174000"]
    )
    document_title: Optional[str] = Field(
        None,
        description="Document title or heading"
    )
    content: str = Field(
        ...,
        description="Document content text"
    )
    content_length: int = Field(
        ...,
        description="Length of content in characters"
    )
    token_count: Optional[int] = Field(
        None,
        description="Number of tokens in the content"
    )
    chunk_index: Optional[int] = Field(
        None,
        description="Index of this chunk within the document"
    )
    section_title: Optional[str] = Field(
        None,
        description="Section or chapter title"
    )
    page_number: Optional[int] = Field(
        None,
        description="Page number in original document"
    )
    content_type: str = Field(
        ...,
        description="Type of content",
        examples=["paragraph", "heading", "table", "list", "code", "image", "metadata"]
    )
    language: Optional[str] = Field(
        None,
        description="Document language"
    )
    confidence_score: Optional[float] = Field(
        None,
        description="Confidence score for content extraction (0.0-1.0)"
    )
    tags: Optional[Dict[str, Any]] = Field(
        None,
        description="Document tags and metadata"
    )
    embedding_model: Optional[str] = Field(
        None,
        description="Model used to generate embeddings"
    )
    embedding_dimensions: Optional[int] = Field(
        None,
        description="Dimensions of the embedding vector"
    )
    vector_id: Optional[str] = Field(
        None,
        description="External vector database ID"
    )
    created_at: datetime = Field(
        ...,
        description="Document creation timestamp"
    )
    updated_at: datetime = Field(
        ...,
        description="Document last update timestamp"
    )

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Schema for paginated document list responses."""
    
    data: List[DocumentResponse] = Field(
        ...,
        description="List of documents"
    )
    pagination: "PaginationMetadata" = Field(
        ...,
        description="Pagination metadata"
    )


# Import here to avoid circular imports
from .common import PaginationMetadata
DocumentListResponse.model_rebuild()
