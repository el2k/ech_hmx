"""
用于RAG文档生成的网站爬取任务。
该模块提供用于单页爬取并支持层级页面发现的Celery任务。每个页面独立进行抓取，子页面将被创建并作为新任务加入队列。
设计:
-crawl_page_task:爬取单个页面，创建文件，发现子页面。
每个页面追踪父页ID以构建树状结构
爬取配置存储在Collection.crawl_config中。
性能优化:使用单事务批量创建子页面通过缓存页面计数来减少数据库往返次数对子页面使用批量任务队列
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select

from .celery_app import celery_app
from ..config import get_settings
from ..database import get_db_session, reset_db_state
from ..logging_config import get_logger
from ..models import Collection, File, WebsitePage
from ..services.crawler import CrawlOptions, WebCrawlerService, url_hash

logger = get_logger(__name__)
settings = get_settings()

@dataclass
class PageInfo:
    """Container for page information used during crawling."""
    id: UUID
    url: str
    depth: int
    collection_id: UUID
    project_id: UUID
    crawl_config: Optional[Dict[str, Any]]

@dataclass
class CrawlConfig:
    """Parsed crawl configuration with defaults."""
    max_depth: int
    max_pages: int
    include_patterns: List[str]
    exclude_patterns: List[str]
    render_js: bool
    delay_seconds: float
    user_agent: Optional[str]
    timeout_seconds: int
    @classmethod
    def from_dict(cls, config: Dict[str, Any], max_depth_override: Optional[int] = None) -> "CrawlConfig":
        """Create CrawlConfig from dictionary with defaults."""
        # cls 指向 CrawlConfig 类本身，允许我们在类方法中创建类的实例。
        return cls(
            max_depth=max_depth_override if max_depth_override is not None else config.get("max_depth", 3),
            max_pages=config.get("max_pages", 100),
            include_patterns=config.get("include_patterns", []),
            exclude_patterns=config.get("exclude_patterns", []),
            render_js=config.get("render_js", False),
            delay_seconds=config.get("delay_seconds", 1.0),
            user_agent=config.get("user_agent"),
            timeout_seconds=config.get("timeout_seconds", 30),
        )
# 合并爬取配置，优先级为页面级别配置。
#参数:
#collection_config:来自Collection.crawl_config的基配置;page_config:来自WebsitePage.crawl_config的覆盖配置。
#返回值: 合并的配置字典，其中页面配置值覆盖集合配置值。
def merge_crawl_configs(
    collection_config: Optional[Dict[str, Any]],
    page_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Merge crawl configurations with page-level config taking priority.

    Args:
        collection_config: Base configuration from Collection.crawl_config
        page_config: Override configuration from WebsitePage.crawl_config

    Returns:
        Merged configuration dictionary where page_config values override
        collection_config values for the same keys.
    """
    return {**(collection_config or {}), **(page_config or {})}    

# 加载页面和配置的异步函数，从数据库中获取页面信息和爬取配置。
async def _load_page_and_config(
    page_id: UUID,
    max_depth_override: Optional[int] = None,
) -> tuple[Optional[PageInfo], Optional[CrawlConfig], Optional[str]]:
    """
    Load page and collection configuration from database.

    Returns:
        Tuple of (page_info, crawl_config, error_message)
        If error_message is set, page_info and crawl_config will be None.
    """
    async with get_db_session() as db:
        result = await db.execute(
            select(WebsitePage).where(WebsitePage.id == page_id)
        )
        page = result.scalar_one_or_none()

        if not page:
            return None, None, "Page not found"

        if page.status not in ("pending", "retry"):
            return None, None, f"invalid_status: {page.status}"

        # Load collection for configuration
        coll_result = await db.execute(
            select(Collection).where(Collection.id == page.collection_id)
        )
        collection = coll_result.scalar_one_or_none()

        if not collection:
            return None, None, "Collection not found"

        # Merge and parse crawl configurations
        merged_config = merge_crawl_configs(collection.crawl_config, page.crawl_config)
        crawl_config = CrawlConfig.from_dict(merged_config, max_depth_override)

        page_info = PageInfo(
            id=page.id,
            url=page.url,
            depth=page.depth,
            collection_id=page.collection_id,
            project_id=page.project_id,
            crawl_config=page.crawl_config,
        )

        # Update status to crawling
        page.status = "crawling"
        await db.commit()

    return page_info, crawl_config, None

async def _update_page_status(
    page_id: UUID,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Update page status in database."""
    async with get_db_session() as db:
        result = await db.execute(select(WebsitePage).where(WebsitePage.id == page_id))
        page = result.scalar_one_or_none()
        if page:
            page.status = status
            if error_message:
                page.error_message = error_message
            await db.commit()

async def crawl_page_async(
    page_id: UUID,
    auto_discover: bool = True,
    max_depth: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Async function to crawl a single page.

    This function handles:
    1. Load page and collection configuration
    2. Crawl the page content
    3. Save content and create File record
    4. Discover and create child pages (if auto_discover)
    5. Trigger document processing
    6. Update page status

    Args:
        page_id: UUID of the page to crawl
        auto_discover: Whether to automatically create child page tasks
        max_depth: Override max depth (uses collection config if None)

    Returns:
        Dictionary containing crawl results
    """
    try:
        # Step 1: Load page and collection info
        page_info, crawl_config, error = await _load_page_and_config(page_id, max_depth)

        if error:
            if error.startswith("invalid_status"):
                logger.warning(f"Page {page_id} {error}, skipping")
                return {"page_id": str(page_id), "status": "skipped", "reason": error}
            logger.error(f"Page {page_id}: {error}")
            return {"page_id": str(page_id), "status": "failed", "error": error}

        # Step 2: Check depth limit
        if page_info.depth > crawl_config.max_depth:
            await _update_page_status(
                page_id, "skipped",
                f"Exceeded max depth: {page_info.depth} > {crawl_config.max_depth}"
            )
            return {"page_id": str(page_id), "status": "skipped", "reason": "max_depth_exceeded"}

        # Step 3: Initialize crawler and crawl the page
        # 初始化爬虫并抓取页面内容
        options = CrawlOptions(
            render_js=crawl_config.render_js,
            delay_seconds=crawl_config.delay_seconds,
            user_agent=crawl_config.user_agent,
            timeout_seconds=crawl_config.timeout_seconds,
        )

        crawler = WebCrawlerService(
            options=options,
            include_patterns=crawl_config.include_patterns,
            exclude_patterns=crawl_config.exclude_patterns,
        )

        crawled_page = await crawler.crawl_page(page_info.url, depth=page_info.depth)

        # Handle crawl failure
        if not crawled_page:
            await _update_page_status(page_id, "failed", "Crawl returned empty result")
            return {"page_id": str(page_id), "status": "failed", "error": "empty_result"}

        # Step 4: Save crawl results and create File
        # 保存爬取结果并创建 File 记录
        file_id = None
        async with get_db_session() as db:
            result = await db.execute(select(WebsitePage).where(WebsitePage.id == page_id))
            page = result.scalar_one()

            # Update page with crawled content
            page.title = crawled_page.title
            page.content_markdown = crawled_page.content_markdown
            page.content_length = crawled_page.content_length
            page.content_hash = crawled_page.content_hash
            page.meta_description = crawled_page.meta_description
            page.http_status_code = crawled_page.http_status_code
            page.discovered_links = [
                {"url": link, "created": False}
                for link in crawled_page.links
            ]
            page.status = "fetched"

            # Create File record if content exists
            # 创建 File 记录（如果内容有效）
            if crawled_page.content_markdown and crawled_page.content_length > 0:
                file_id = uuid4()
                safe_title = (crawled_page.title or "page")[:100].replace("/", "_").replace("\\", "_")
                filename = f"{safe_title}_{file_id}.md"
                storage_path = os.path.join(settings.upload_dir, str(file_id))

                os.makedirs(os.path.dirname(storage_path) if os.path.dirname(storage_path) else settings.upload_dir, exist_ok=True)
                with open(storage_path, "w", encoding="utf-8") as f:
                    f.write(crawled_page.content_markdown)

                file_record = File(
                    id=file_id,
                    project_id=page_info.project_id,
                    collection_id=page_info.collection_id,
                    original_filename=filename,
                    file_size=len(crawled_page.content_markdown.encode("utf-8")),
                    content_type="text/markdown",
                    storage_provider="local",
                    storage_path=storage_path,
                    storage_metadata={
                        "source": "website_crawl",
                        "source_url": page_info.url,
                        "page_id": str(page_id),
                    },
                    status="pending",
                    description=crawled_page.meta_description,
                )
                db.add(file_record)

                page.file_id = file_id
                page.status = "extracted"

            await db.commit()

        # Step 5: Discover and create child pages (optimized batch processing)
        # 自动发现并创建子页面任务（核心亮点）
        children_created = 0
        max_pages_reached = False
        created_child_ids: List[UUID] = []
        # 如果 auto_discover 为 True 且当前页面深度小于最大深度，则进行子页面发现
        if auto_discover and page_info.depth < crawl_config.max_depth:
            # Filter links first (no DB access needed)
            valid_links = crawler.filter_links(crawled_page.links, page_info.url)

            if valid_links:
                # Single transaction for all child page operations
                async with get_db_session() as db:
                    # Get current page count once
                    # 页面数量配额检查
                    current_page_count = await db.scalar(
                        select(func.count()).select_from(WebsitePage).where(
                            WebsitePage.collection_id == page_info.collection_id
                        )
                    )

                    max_pages = crawl_config.max_pages

                    if current_page_count >= max_pages:
                        logger.info(
                            f"Collection {page_info.collection_id} reached max_pages limit "
                            f"({current_page_count}/{max_pages}), skipping child discovery"
                        )
                        max_pages_reached = True
                    else:
                        remaining_quota = max_pages - current_page_count

                        # Limit valid_links to remaining quota
                        if len(valid_links) > remaining_quota:
                            logger.info(
                                f"Limiting child pages from {len(valid_links)} to {remaining_quota} "
                                f"(max_pages={max_pages}, current={current_page_count})"
                            )
                            valid_links = valid_links[:remaining_quota]

                        # Batch check for existing URLs - get all existing hashes in one query
                        # 批量去重检查（一次查询搞定）
                        link_hashes = {url_hash(link): link for link in valid_links}
                        existing_result = await db.execute(
                            select(WebsitePage.url_hash).where(
                                and_(
                                    WebsitePage.collection_id == page_info.collection_id,
                                    WebsitePage.url_hash.in_(list(link_hashes.keys())),
                                )
                            )
                        )
                        existing_hashes = set(row[0] for row in existing_result.fetchall())

                        # Filter out existing URLs
                        new_links = [
                            (h, url) for h, url in link_hashes.items()
                            if h not in existing_hashes
                        ]

                        # Build child crawl config once
                        child_crawl_config = None
                        if page_info.crawl_config and "max_depth" in page_info.crawl_config:
                            child_crawl_config = {"max_depth": page_info.crawl_config["max_depth"]}

                        # Batch create child pages
                        # 批量创建子页面
                        '''为每个新链接创建 WebsitePage 记录，深度 +1，状态为 "pending"，爬取来源标记为 "discovered"
                            所有记录先 add + flush（获取自增 ID），最后统一 commit'''
                        for link_hash, link_url in new_links:
                            child_page = WebsitePage(
                                collection_id=page_info.collection_id,
                                project_id=page_info.project_id,
                                parent_page_id=page_id,
                                url=link_url,
                                url_hash=link_hash,
                                depth=page_info.depth + 1,
                                status="pending",
                                crawl_source="discovered",
                                crawl_config=child_crawl_config,
                            )
                            db.add(child_page)
                            await db.flush()  # Get the ID
                            created_child_ids.append(child_page.id)
                            children_created += 1

                        # Single commit for all child pages
                        if children_created > 0:
                            await db.commit()

                # Queue child tasks outside the DB session
                for child_id in created_child_ids:
                    crawl_page_task.delay(
                        str(child_id),
                        auto_discover=True,
                        max_depth=crawl_config.max_depth,
                    )

                # Update discovered_links to mark created ones
                # 更新 discovered_links 标记
                if children_created > 0:
                    created_urls = {link_hashes[h] for h, _ in new_links[:children_created]}
                    async with get_db_session() as db:
                        result = await db.execute(select(WebsitePage).where(WebsitePage.id == page_id))
                        page = result.scalar_one()
                        if page.discovered_links:
                            for link_info in page.discovered_links:
                                if link_info["url"] in created_urls:
                                    link_info["created"] = True
                        await db.commit()

        # Step 6: Trigger document processing
        # 触发文档处理,如果成功创建了 File 记录，通过 process_file_task.delay() 异步触发文档处理任务（可能是分块、向量化、入库等后续流程）
        if file_id:
            from .document_processing import process_file_task
            process_file_task.delay(str(file_id), str(page_info.collection_id))
            await _update_page_status(page_id, "processing")

        logger.info(
            f"Crawled page {page_id}: {crawled_page.content_length} chars, "
            f"{len(crawled_page.links)} links, {children_created} children created"
            f"{' (max_pages reached)' if max_pages_reached else ''}"
        )

        return {
            "page_id": str(page_id),
            "url": page_info.url,
            "status": "success",
            "content_length": crawled_page.content_length,
            "links_discovered": len(crawled_page.links),
            "children_created": children_created,
            "file_id": str(file_id) if file_id else None,
            "max_pages_reached": max_pages_reached,
        }

    except Exception as e:
        logger.error(f"Error crawling page {page_id}: {e}")
        await _update_page_status(page_id, "failed", str(e))
        return {
            "page_id": str(page_id),
            "status": "failed",
            "error": str(e),
        }


@celery_app.task(bind=True, name="crawl_page_task")
def crawl_page_task(
    self,
    page_id: str,
    auto_discover: bool = True,
    max_depth: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Celery task for crawling a single page.

    This task handles:
    1. Crawl the page content using crawl4ai
    2. Save content and create File record
    3. Discover child links and create child page records
    4. Queue child pages for crawling (if auto_discover)
    5. Trigger document processing

    Args:
        page_id: UUID string of the page to crawl
        auto_discover: Whether to automatically discover and crawl child pages
        max_depth: Override max crawl depth (uses collection config if None)

    Returns:
        Dictionary containing crawl results
    """
    try:
        page_uuid = UUID(page_id)

        # Reset database state for Celery worker
        reset_db_state()

        # Run async crawling
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                crawl_page_async(
                    page_id=page_uuid,
                    auto_discover=auto_discover,
                    max_depth=max_depth,
                )
            )
            return result
        finally:
            # Clean up database connections before closing the loop
            reset_db_state()
            loop.close()

    except Exception as e:
        logger.error(f"Crawl page task failed for {page_id}: {e}")
        return {
            "page_id": page_id,
            "status": "failed",
            "error": str(e),
        }
