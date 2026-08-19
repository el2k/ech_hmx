# 这段代码是基于 Pydantic v1/v2 的数据模型（Schema）定义，专门用于搜索模块的请求 / 响应数据结构校验与标准化。
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# 定义单条搜索结果的数据结构。
class SearchResult(BaseModel):
    """Schema for individual search results."""

    document_id: UUID = Field(
        ...,
        description="Document unique identifier"
    )
    # QA 对（问答对）可能没有原始文件，所以 file_id=None
    file_id: Optional[UUID] = Field(
        None,
        description="Associated file ID (None for QA pairs)"
    )
    # collection_id 用于知识库、向量库分组
    collection_id: Optional[UUID] = Field(
        None,
        description="Associated collection ID"
    )
    # 相关性评分，0~1 标准化，语义搜索 / 混合搜索都会返回该分数
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Relevance score (0-1, higher is more relevant)"
    )
    # 文档片段预览，前端直接展示
    content_preview: str = Field(
        ...,
        description="Preview of the document content"
    )
    document_title: Optional[str] = Field(
        None,
        description="Document title or heading"
    )
    # 内容类型枚举示例，前端可根据类型做不同样式渲染
    content_type: str = Field(
        ...,
        description="Type of content",
        examples=["paragraph", "heading", "table", "list", "code", "image", "metadata"]
    )
    # chunk 索引 page原始页码 section章节标题
    chunk_index: Optional[int] = Field(
        None,
        description="Index of this chunk within the document"
    )
    page_number: Optional[int] = Field(
        None,
        description="Page number in original document"
    )
    section_title: Optional[str] = Field(
        None,
        description="Section or chapter title"
    )
    # 扩展字段，用于存放业务标签、来源、作者、权限等
    tags: Optional[Dict[str, Any]] = Field(
        None,
        description="Document tags and metadata"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional metadata including source info"
    )
    created_at: datetime = Field(
        ...,
        description="Document creation timestamp"
    )
# 搜索本身的元信息，用于前端展示、日志、监控、调试。
class SearchMetadata(BaseModel):
    """Schema for search metadata."""
    
    query: str = Field(
        ...,
        description="Original search query"
    )
    # 搜索结果总数、返回结果数、搜索耗时、应用的过滤器、搜索类型等信息
    total_results: int = Field(
        ...,
        ge=0,
        description="Total number of results found"
    )
    returned_results: int = Field(
        ...,
        ge=0,
        description="Number of results returned in this response"
    )
    search_time_ms: int = Field(
        ...,
        ge=0,
        description="Search execution time in milliseconds"
    )
    filters_applied: Optional[Dict[str, Any]] = Field(
        None,
        description="Filters that were applied to the search"
    )
    # 默认：语义搜索 支持关键词、混合搜索
    # 便于后端区分检索策略、做 A/B 测试
    search_type: str = Field(
        default="semantic",
        description="Type of search performed",
        examples=["semantic", "keyword", "hybrid"]
    )

# 顶层返回结构，是 API 真正返回给前端的完整结构体。
class SearchResponse(BaseModel):
    """Schema for search responses."""
    
    results: List[SearchResult] = Field(
        ...,
        description="List of search results"
    )
    search_metadata: SearchMetadata = Field(
        ...,
        description="Search execution metadata"
    )