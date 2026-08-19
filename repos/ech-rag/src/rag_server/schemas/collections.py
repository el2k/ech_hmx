"""
Collection-related Pydantic schemas.
"""
import enum
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field
# RAG（检索增强生成）系统设计的核心业务模型。
# 这段代码定义了一个枚举类 CollectionTypeEnum，用于表示集合（Collection）的类型或来源。
class CollectionTypeEnum(str, enum.Enum):
    file = "file"       # 文件上传
    website = "website" # 网站爬取
    qa = "qa"           # 问答对
    # 约束数据输入：在 RAG 系统中，数据的来源决定了后续的解析、分块（Chunking）和 Embedding 策略。
    # 使用枚举而不是随意的字符串，可以在代码入口处（如 Pydantic 模型校验）就拦截非法的类型，保证数据的纯洁性。

# RAG 系统中“创建知识库”这个 API 接口的数据校验器和文档生成器。
# 它详细规定了前端或用户在创建一个新的 Collection（知识库/项目）时，必须提供哪些数据，以及这些数据需要满足什么格式。
class CollectionCreateRequest(BaseModel):
    display_name: str = Field(...,min_length=1, max_length=255, description="Human-readable name for the collection.",example=["Product Documentation v2.1", "Research Papers"])
    description: Optional[str] = Field(None,description="Type of collection: file, website, or qa",example=["file"])
    crawl_config: Optional[Dict[str, Any]] = Field(
            None,
            description="""Crawl configuration for website collections (only used when collection_type is 'website').
    
    Available configuration options:
    - **start_url** (str, required): Starting URL for crawling
    - **max_pages** (int): Maximum number of pages to crawl (default: 100)
    - **max_depth** (int): Maximum crawl depth from start URL (default: 3)
    - **include_patterns** (list[str]): URL glob patterns to include (e.g., '*/docs/*')
    - **exclude_patterns** (list[str]): URL glob patterns to exclude (e.g., '*/admin/*')
    - **wait_for_selector** (str): CSS selector to wait for before extracting content
    - **timeout** (int): Page load timeout in seconds (default: 30)
    - **delay_between_requests** (float): Delay between requests in seconds (default: 1.0)
    - **respect_robots_txt** (bool): Whether to respect robots.txt (default: true)
    - **user_agent** (str): Custom user agent string
    - **headers** (dict): Custom HTTP headers
    - **js_rendering** (bool): Whether to render JavaScript (default: true)
    - **extract_images** (bool): Whether to extract image URLs (default: false)
    - **extract_links** (bool): Whether to extract external links (default: true)
    """,
            examples=[
                {
                    "start_url": "https://docs.example.com",
                    "max_pages": 100,
                    "max_depth": 3,
                    "include_patterns": ["*/docs/*", "*/guide/*"],
                    "exclude_patterns": ["*/admin/*", "*/login/*"],
                    "wait_for_selector": ".main-content",
                    "timeout": 30,
                    "delay_between_requests": 1.0,
                    "respect_robots_txt": True,
                    "js_rendering": True,
                    "extract_links": True
                }
            ]
        )
    collection_metadata: Optional[Dict[str, Any]] = Field(
            None,
            description="Collection metadata (embedding model, chunk size, etc.)",
            examples=[
                {
                    "embedding_model": "text-embedding-ada-002",
                    "chunk_size": 1000,
                    "chunk_overlap": 200,
                    "language": "en"
                }
            ]
        )
    tags: Optional[List[str]] = Field(
            None,
            description="Collection tags for categorization and filtering",
            examples=[["documentation", "product", "v2.1"]]
        )

# 它是专门用于更新（PATCH/PUT）现有知识库的 Pydantic 数据校验模型。
# Update 模型：所有字段都是可选的 
# 更新CollectionCreateRequest的字段是可选的，这意味着用户可以只更新他们想要修改的部分，而不需要提供完整的collectionCreateRequest数据.
class CollectionUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=255, description="Human-readable name for the collection.", example=["Product Documentation v2.2"])
    description: Optional[str] = Field(None, description="Description of the collection.", example=["Updated description for the collection."])
    collection_type: Optional[CollectionTypeEnum] = Field(None, description="Type of collection: file, website, or qa", example=["file"])
    crawl_config: Optional[Dict[str, Any]] = Field(
        None,
        description="""Crawl configuration for website collections. See CollectionCreateRequest for full option list.
       
       Common options to update:
       - **max_pages**: Maximum number of pages to crawl
       - **max_depth**: Maximum crawl depth from start URL
       - **include_patterns** / **exclude_patterns**: URL filtering patterns
       - **timeout**: Page load timeout in seconds
       - **delay_between_requests**: Delay between requests
       """,
        examples=[
                   {
                       "max_pages": 200,
                       "max_depth": 5,
                       "include_patterns": ["*/docs/*", "*/api/*"],
                       "exclude_patterns": ["*/admin/*", "*/login/*"],
                       "delay_between_requests": 2.0
                   }
               ]
    )
    collection_metadata: Optional[Dict[str, Any]] = Field(
            None,
            description="Collection metadata (embedding model, chunk size, etc.)",
            examples=[
                {
                    "embedding_model": "text-embedding-ada-002",
                    "chunk_size": 1200,
                    "chunk_overlap": 250,
                    "language": "en"
                }
            ]
        )
    tags: Optional[List[str]] = Field(
            None,
            description="Collection tags for categorization and filtering",
            examples=[["documentation", "product", "v2.2", "updated"]]
        )

# 这段代码定义了 CollectionResponse，它是专门用于API 响应的 Pydantic 模型。    
# 它包含了 Collection 的所有关键信息，包括 ID、名称、描述、类型、爬取配置、元数据、标签以及创建和更新时间。
class CollectionResponse(BaseModel):
    """Schema for collection API responses."""

    id: UUID = Field(
        ...,
        description="Collection unique identifier",
        examples=["coll_123e4567-e89b-12d3-a456-426614174000"]
    )
    display_name: str = Field(
        ...,
        description="Human-readable collection name",
        examples=["Product Documentation v2.1"]
    )
    description: Optional[str] = Field(
        None,
        description="Collection description",
        examples=["Updated product documentation for RAG knowledge base"]
    )
    collection_type: CollectionTypeEnum = Field(
        ...,
        description="Type of collection: file, website, or qa",
        examples=["file"]
    )
    crawl_config: Optional[Dict[str, Any]] = Field(
        None,
        description="""Crawl configuration for website collections. Only present when collection_type is 'website'.

Contains settings such as:
- start_url, max_pages, max_depth
- include_patterns, exclude_patterns
- timeout, delay_between_requests
- js_rendering, extract_images, extract_links
""",
        examples=[
            {
                "start_url": "https://docs.example.com",
                "max_pages": 100,
                "max_depth": 3,
                "include_patterns": ["*/docs/*"],
                "exclude_patterns": ["*/admin/*"],
                "js_rendering": True
            }
        ]
    )
    collection_metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="Collection metadata",
        examples=[
            {
                "embedding_model": "text-embedding-ada-002",
                "chunk_size": 1000,
                "chunk_overlap": 200,
                "language": "en"
            }
        ]
    )
    tags: Optional[List[str]] = Field(
        None,
        description="Collection tags for categorization and filtering",
        examples=[["documentation", "product", "v2.1"]]
    )
    created_at: datetime = Field(
        ...,
        description="Collection creation timestamp",
        examples=["2024-01-15T10:30:00Z"]
    )
    updated_at: datetime = Field(
        ...,
        description="Collection last update timestamp",
        examples=["2024-01-15T10:30:00Z"]
    )
    deleted_at: Optional[datetime] = Field(
        None,
        description="Collection deletion timestamp (if soft deleted)"
    )
    file_count: int = Field(
        ...,
        ge=0,
        description="Total number of files associated with this collection",
        examples=[15]
    )

    class Config:
        from_attributes = True

# 这段代码定义了 CollectionStats，它是专门用于展示集合（知识库）统计数据的 Pydantic 响应模型。
class CollectionStats(BaseModel):
    document_count: int = Field(
        ...,
        ge=0,
        description="Total number of documents in the collection",
        examples=[150]
    )
    file_count: int = Field(
        ...,
        ge=0,
        description="Total number of files in the collection",
        examples=[25]
    )
    total_tokens: int = Field(
        ...,
        ge=0,
        description="Total number of tokens across all documents in the collection",
        examples=[45000]
    )
    last_updated: Optional[datetime] = Field(
        None,
        description="Timestamp of the last update to the collection's documents",
        examples=["2024-01-15T10:30:00Z"]
    )

# 这段代码定义了 CollectionDetailResponse，它是专门用于展示集合（知识库）详细信息的 Pydantic 响应模型。
class CollectionDetailResponse(CollectionResponse):
    """Schema for detailed collection response with optional statistics."""
    
    stats: Optional[CollectionStats] = Field(
        None,
        description="Collection statistics (when include_stats=true)"
    )

# 它是 RAG（检索增强生成）系统中最核心的搜索查询输入模型。
class CollectionSearchRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Search query text",
        examples=["how to integrate RAG with existing systems"]
    )
    limit: int = Field(
        10,
        ge=1,
        le=100,
        description="Maximum number of search results to return",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Number of results to skip for pagination",
    )
    min_score: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score for search results (0.0 to 1.0)",
    )
    filters: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional filters to apply to search results",
                examples=[
                    {
                        "content_type": ["paragraph", "heading"],
                        "language": "en",
                        "min_confidence": 0.8,
                        "tags": {"section": "installation"}
                    }
                ]
            )
    search_mode: str = Field(
                default="hybrid",
                description="Search mode: 'hybrid' (default), 'embedding', or 'fulltext'",
                examples=["hybrid"]
            )
# 这段代码定义了 CollectionListResponse，它是专门用于分页返回集合（知识库）列表的 Pydantic 响应模型。
class CollectionListResponse(BaseModel):
    """Schema for paginated collection list responses."""

    data: List[CollectionResponse] = Field(
        ...,
        description="List of collections"
    )
    pagination: "PaginationMetadata" = Field(
        ...,
        description="Pagination metadata"
    )
# 这段代码定义了 CollectionBatchRequest，它是专门用于批量请求集合（知识库）信息的 Pydantic 请求模型。
class CollectionBatchRequest(BaseModel):
    """Schema for batch collection retrieval requests."""

    collection_ids: List[UUID] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of collection UUIDs to retrieve (maximum 50 collections per request)",
        examples=[
            [
                "coll_123e4567-e89b-12d3-a456-426614174000",
                "coll_987fcdeb-51a2-43d7-8f9e-123456789abc",
                "coll_456789ab-cdef-1234-5678-9abcdef01234"
            ]
        ]
    )
# 这段代码定义了 CollectionBatchResponse，它是专门用于批量返回集合（知识库）信息的 Pydantic 响应模型。
class CollectionBatchResponse(BaseModel):
    """Schema for batch collection retrieval responses."""

    collections: List[CollectionResponse] = Field(
        ...,
        description="List of successfully retrieved collections with full details"
    )
    not_found: List[UUID] = Field(
        ...,
        description="List of collection IDs that were not found or not accessible"
    )
    total_requested: int = Field(
        ...,
        ge=1,
        description="Total number of collection IDs requested",
        examples=[3]
    )
    total_found: int = Field(
        ...,
        ge=0,
        description="Total number of collections successfully retrieved",
        examples=[2]
    )


# Import here to avoid circular imports
from .common import PaginationMetadata
# 这里的model_rebuild()方法是 Pydantic v2 中的新特性，用于在模型定义后重新构建模型的内部结构。
CollectionListResponse.model_rebuild()

