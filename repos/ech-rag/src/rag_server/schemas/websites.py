# 这段代码是网站爬虫 / 网页采集系统的 Pydantic 数据校验模型
'''
整体结构分为 5 大模块：
爬虫配置（CrawlOptionsSchema）
单页添加接口（请求 + 响应）
网页详情与树形结构（WebsitePageResponse）
深度爬取接口（CrawlDeeper）
爬取进度统计（CrawlProgressSchema）
'''

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl
# 爬虫配置模型 CrawlOptionsSchema,用于控制爬虫行为，可覆盖集合级默认配置。
class CrawlOptionsSchema(BaseModel):
    """Schema for crawl configuration options."""
    # 是否启用无头浏览器渲染 JS ,适用于动态页面、React/Vue 渲染的内容
    render_js: bool = Field(
        default=False,
        description="Whether to render JavaScript (uses headless browser)",
    )
    # 是否遵守网站爬虫协议,合规性设计
    respect_robots_txt: bool = Field(
        default=True,
        description="Whether to respect robots.txt rules",
    )
    # 请求间隔，防封
    delay_seconds: float = Field(
        default=1.0,
        ge=0,
        le=60,
        description="Delay between requests in seconds",
    )
    # 自定义 UA，模拟浏览器 / 设备
    user_agent: Optional[str] = Field(
        default=None,
        description="Custom user agent string",
    )
    # 请求超时 5~300s,防止长时间阻塞
    timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Request timeout in seconds",
    )
    # 自定义请求头（Cookie、Referer、Auth 等）
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Custom HTTP headers",
    )

# AddPageRequest（添加页面请求）
class AddPageRequest(BaseModel):
    """Schema for adding a page to crawl."""
    # 要爬取的页面，自动校验 URL 格式
    url: HttpUrl = Field(
        ...,
        description="URL of the page to add",
        examples=["https://docs.python.org/3/"],
    )
    # 构建页面层级树，子页面深度 = 父深度 +1
    parent_page_id: Optional[UUID] = Field(
        default=None,
        description="Parent page ID. If provided, the new page will be a child of this page with depth = parent.depth + 1",
    )
    # 只爬当前页；=1 爬当前 + 子链接；最多 10 层防失控
    max_depth: int = Field(
        default=0,
        ge=0,
        le=10,
        description="Maximum crawl depth from this page (0 = only this page)",
    )
    # glob 模式白名单 / 黑名单，控制爬取范围
    include_patterns: Optional[List[str]] = Field(
        default=None,
        description="URL patterns to include (glob patterns)",
    )
    exclude_patterns: Optional[List[str]] = Field(
        default=None,
        description="URL patterns to exclude (glob patterns)",
    )
    # 单页独立爬虫配置
    options: Optional[CrawlOptionsSchema] = Field(
        default=None,
        description="Crawl options (overrides collection defaults)",
    )
# 添加页面响应
class AddPageResponse(BaseModel):
    """Schema for add page response."""
    # 新增成功
    success: bool = Field(
        ...,
        description="Whether the page was added successfully",
    )
    page_id: Optional[UUID] = Field(
        None,
        description="ID of the newly created page (if added)",
    )
    message: str = Field(
        ...,
        description="Status message",
    )
    # status 枚举含义：added：新增成功 exists：已存在 crawling：正在爬取
    status: str = Field(
        ...,
        description="Result status: 'added', 'exists', 'crawling'",
    )
# 这是整个爬虫系统的核心数据结构，记录单页面完整生命周期状态。
class WebsitePageResponse(BaseModel):
    """Schema for website page API responses."""

    id: UUID = Field(
        ...,
        description="Page unique identifier",
    )
    collection_id: UUID = Field(
        ...,
        description="Associated collection ID",
    )
    parent_page_id: Optional[UUID] = Field(
        None,
        description="Parent page ID (for hierarchical structure)",
    )
    url: str = Field(
        ...,
        description="Page URL",
    )
    title: Optional[str] = Field(
        None,
        description="Page title",
    )
    depth: int = Field(
        ...,
        description="Crawl depth from root page",
    )
    # 文本长度
    content_length: int = Field(
        ...,
        description="Content length in characters",
    )
    # 页面元描述
    meta_description: Optional[str] = Field(
        None,
        description="Page meta description",
    )
    # 标准状态机：
    # pending → crawling → fetched → extracted → processing → processed → failed / skipped
    # 待爬取,抓取中,已下载,已抽取,文本处理中（向量化 / 分块）,已入库,失败 / 跳过
    status: str = Field(
        ...,
        description="Page status: pending, crawling, fetched, extracted, processing, processed, failed, skipped",
    )
    # 页面来源，初始添加 / 发现 / 手动添加 / 深度爬取
    crawl_source: Optional[str] = Field(
        None,
        description="How this page was added: initial, discovered, manual, deep_crawl",
    )
    # # 200/404/500/403
    http_status_code: Optional[int] = Field(
        None,
        description="HTTP response status code",
    )
    # 抽取后存入文件库
    file_id: Optional[UUID] = Field(
        None,
        description="Associated file ID (after processing)",
    )
     # 页面发现的子链接 
    discovered_links: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Links discovered on this page",
    )
    # 失败原因
    error_message: Optional[str] = Field(
        None,
        description="Error message if processing failed",
    )
    # 页面树是否已完成处理
    tree_completed: bool = Field(
        default=False,
        description="Whether this page and all its descendant pages have been processed or skipped",
    )
    # 是否有子页面
    has_children: bool = Field(
        default=False,
        description="Whether this page has any child pages",
    )
    # 子页面列表，只有在 tree_depth > 0 时才会返回
    children: Optional[List["WebsitePageResponse"]] = Field(
        default=None,
        description="Child pages (populated when tree_depth > 0)",
    )
    # 页面创建时间
    created_at: datetime = Field(
        ...,
        description="Page creation timestamp",
    )
    # 页面更新时间
    updated_at: datetime = Field(
        ...,
        description="Page last update timestamp",
    )

    class Config:
        from_attributes = True

# Rebuild model to support recursive self-reference
# WebsitePageResponse 包含 children 字段，其类型为自身列表，形成递归树形结构。
# 由于 Python 在类定义期间无法解析未完成的类型，需要调用 model_rebuild()
# 让 Pydantic 在类定义完成后重新解析类型注解，从而支持递归自引用，确保模型序列化、校验与 OpenAPI 文档正常生成。
WebsitePageResponse.model_rebuild()

# 分页网页列表响应
class WebsitePageListResponse(BaseModel):
    """Schema for paginated page list responses."""

    data: List[WebsitePageResponse] = Field(
        ...,
        description="List of pages",
    )
    pagination: "PaginationMetadata" = Field(
        ...,
        description="Pagination metadata",
    )
# 「深度爬取」接口的请求体 & 返回体
'''
用户已经添加过一个页面，现在想从这个页面继续往下挖更深的链接，而不是重新添加一个根页面。
前端点一下：「继续爬取子链接」
后端就接收 CrawlDeeperRequest
执行爬取调度，返回统计结果 CrawlDeeperResponse
'''
class CrawlDeeperRequest(BaseModel):
    """Schema for deep crawl request from an existing page."""

    max_depth: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum crawl depth from this page",
    )
    # 白名单 URL 规则
    include_patterns: Optional[List[str]] = Field(
        default=None,
        description="URL patterns to include (fnmatch style)",
    )
    # 黑名单 URL 规则
    exclude_patterns: Optional[List[str]] = Field(
        default=None,
        description="URL patterns to exclude (fnmatch style)",
    )

# 深度爬取响应
class CrawlDeeperResponse(BaseModel):
    """Schema for deep crawl response."""

    success: bool = Field(
        ...,
        description="Whether the operation was successful",
    )
    # 从哪个页面出发开始深度爬取
    source_page_id: UUID = Field(
        ...,
        description="ID of the source page",
    )
    # 这次操作新加入爬取队列的页面数量
    pages_added: int = Field(
        ...,
        description="Number of new pages added to crawl queue",
    )
    # 这次操作跳过的页面数量（已经存在或正在爬取）
    pages_skipped: int = Field(
        ...,
        description="Number of pages skipped (already exists or crawling)",
    )
    # 在当前页面总共解析出多少个链接
    links_found: int = Field(
        ...,
        description="Total number of links found in the page",
    )
    # 人性化提示信息，例如：
    message: str = Field(
        ...,
        description="Status message",
    )
    # 实际被加入队列的 URL 列表
    added_urls: List[str] = Field(
        default_factory=list,
        description="URLs that were added to crawl queue",
    )

# CrawlProgressSchema 是知识库集合的爬虫进度统计模型，数据由后端根据页面表实时聚合计算得到，
# 不直接存储在数据库，用于前端仪表盘展示爬取任务整体状态、渲染进度条。
class CrawlProgressSchema(BaseModel):
    """Schema for collection crawl progress (computed from pages)."""
    # 集合内全部网页记录总数，包含待爬、处理中、成功、失败所有状态；ge=0 保证数值非负。
    total_pages: int = Field(
        ...,
        ge=0,
        description="Total number of pages in collection",
    )
    # 待爬取页面数，对应页面状态 pending。页面已经加入爬虫队列，但还未发起网络请求。
    pages_pending: int = Field(
        ...,
        ge=0,
        description="Number of pages pending crawl",
    )
    # 抓取完成页面数，状态为 fetched。HTTP 请求完成、网页源码已经下载到系统，但还没有执行文本抽取、分块、向量化
    pages_crawled: int = Field(
        ...,
        ge=0,
        description="Number of pages successfully crawled",
    )
   
    # 处理完成页面数，状态 processed。页面已经完整处理，成功转换为内部文档块，可以参与 RAG 检索，是业务意义上真正可用的数据。
    pages_processed: int = Field(
        ...,
        ge=0,
        description="Number of pages processed into documents",
    )
    # 正在处理的页面数，状态为 extracted / processing。网页已经下载，系统正在执行文本提取、清洗、分块、向量化、写入向量库，属于运行中的任务。
    pages_processing: int = Field(
        ...,
        ge=0,
        description="Number of pages currently being processed",
    )
    # 失败页面总数，包含抓取失败、解析失败、向量化失败等所有异常页面（failed），前端可据此提供失败页面列表入口，支持重试操作。
    pages_failed: int = Field(
        ...,
        ge=0,
        description="Number of pages that failed to process",
    )
    # 整体进度百分比，取值范围 [0,100]。
    progress_percent: float = Field(
        ...,
        ge=0,
        le=100,
        description="Overall progress percentage",
    )


# Import for pagination - avoid circular imports
from .common import PaginationMetadata
WebsitePageListResponse.model_rebuild()
