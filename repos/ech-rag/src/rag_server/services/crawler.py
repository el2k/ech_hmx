"""
Web crawler service using crawl4ai.

This module provides single-page crawling functionality for RAG document generation,
utilizing the crawl4ai library for efficient and LLM-friendly content extraction.

Design: Single-page crawling with link extraction
- Each page is crawled independently
- Links are extracted for discovery of child pages
- Page hierarchy is managed externally (by website_crawling tasks)
"""

import fnmatch
import hashlib
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

from ..logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CrawlOptions:
    """Configuration options for web crawling."""

    render_js: bool = False
    respect_robots_txt: bool = True
    delay_seconds: float = 1.0
    user_agent: Optional[str] = None
    timeout_seconds: int = 30
    headers: Optional[Dict[str, str]] = None


@dataclass
class CrawledPage:
    """Represents a crawled web page."""

    url: str
    url_hash: str
    title: Optional[str]
    content_markdown: str
    content_length: int
    content_hash: str
    meta_description: Optional[str]
    http_status_code: int
    depth: int
    links: List[str] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


def url_hash(url: str) -> str:
    """Generate SHA-256 hash of URL."""
    return hashlib.sha256(url.encode()).hexdigest()


def content_hash(content: str) -> str:
    """Generate SHA-256 hash of content."""
    return hashlib.sha256(content.encode()).hexdigest()


class WebCrawlerService:
    """
    单一页面爬取服务，使用 crawl4ai 进行内容提取和链接发现。
    这个服务提供了异步的单页面爬取功能，适用于 RAG 文档生成。
    功能包括：
    - 内容提取，优化为 Markdown 格式
    - 链接提取，用于发现子页面
    - URL 模式过滤（包含/排除）
    - 可配置的浏览器选项
    """

    def __init__(
        self,
        options: Optional[CrawlOptions] = None,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
    ):
        """
        Initialize crawler service.

        Args:
            options: Crawl configuration options
            include_patterns: URL patterns to include (glob)
            exclude_patterns: URL patterns to exclude (glob)
        """
        self.options = options or CrawlOptions()
        self.include_patterns = include_patterns or []
        self.exclude_patterns = exclude_patterns or []

    def _get_browser_config(self) -> BrowserConfig:
        """Create browser configuration."""
        config = BrowserConfig(
            headless=True,
            verbose=False,
        )

        if self.options.user_agent:
            config.user_agent = self.options.user_agent

        return config

    def _extract_links(self, result, base_url: str) -> List[str]:
        """
        提取并规范化爬取结果中的内部链接。
        参数:
            result: Crawl4ai 结果对象
            base_url: 用于解析相对链接的基础 URL
        返回:
            页面上发现的绝对 URL 列表
        """

        links = []
        if not result.links:
            return links

        base_domain = urlparse(base_url).netloc

        for link_info in result.links.get("internal", []):
            link_url = link_info.get("href") if isinstance(link_info, dict) else str(link_info)
            if not link_url:
                continue

            # Resolve relative URLs
            if not link_url.startswith(("http://", "https://")):
                link_url = urljoin(base_url, link_url)

            # Parse and validate
            parsed = urlparse(link_url)

            # Skip non-http(s) URLs
            if parsed.scheme not in ("http", "https"):
                continue

            # Skip external links
            if parsed.netloc != base_domain:
                continue

            # Skip fragments and certain patterns
            if link_url.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            # Normalize: remove fragments
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                normalized += f"?{parsed.query}"

            links.append(normalized)

        return list(set(links))  # Deduplicate

    def _build_crawled_page(self, result, url: str, depth: int) -> CrawledPage:
        """Build CrawledPage from crawl4ai result."""
        markdown_content = result.markdown or ""
        metadata = result.metadata or {}

        return CrawledPage(
            url=result.url or url,
            url_hash=url_hash(result.url or url),
            title=metadata.get("title"),
            content_markdown=markdown_content,
            content_length=len(markdown_content),
            content_hash=content_hash(markdown_content),
            meta_description=metadata.get("description"),
            http_status_code=result.status_code or 200,
            depth=depth,
            links=self._extract_links(result, result.url or url),
            metadata={
                "crawled_at": time.time(),
                "word_count": len(markdown_content.split()),
                "score": metadata.get("score"),
            }
        )

    def should_crawl_url(self, url: str) -> bool:
        """
        Check if URL should be crawled based on include/exclude patterns.

        Args:
            url: URL to check

        Returns:
            True if URL should be crawled
        """
        # Check exclude patterns first
        for pattern in self.exclude_patterns:
            if fnmatch.fnmatch(url, pattern):
                return False

        # If include patterns exist, URL must match at least one
        if self.include_patterns:
            return any(fnmatch.fnmatch(url, p) for p in self.include_patterns)

        return True

    def filter_links(self, links: List[str], base_url: str) -> List[str]:
        """
        Filter discovered links based on patterns and domain.

        Args:
            links: List of discovered URLs
            base_url: Base URL to determine domain

        Returns:
            Filtered list of URLs to crawl
        """
        base_domain = urlparse(base_url).netloc
        valid_links = []

        for link in links:
            # Must be same domain
            if urlparse(link).netloc != base_domain:
                continue

            # Must pass include/exclude filters
            if not self.should_crawl_url(link):
                continue

            valid_links.append(link)

        return valid_links

    async def crawl_page(self, url: str, depth: int = 0) -> Optional[CrawledPage]:
        """
        Crawl a single page using crawl4ai.

        Args:
            url: URL to crawl
            depth: Current depth from root page

        Returns:
            CrawledPage object or None if crawl failed
        """
        logger.info(f"Crawling page: {url} (depth={depth})")

        try:
            run_config = CrawlerRunConfig(
                word_count_threshold=10,
                remove_overlay_elements=True,
                exclude_external_links=True,
            )

            async with AsyncWebCrawler(config=self._get_browser_config()) as crawler:
                result = await crawler.arun(url=url, config=run_config)

                if not result.success:
                    logger.warning(f"Failed to crawl {url}: {result.error_message}")
                    return None

                page = self._build_crawled_page(result, url, depth)
                logger.info(
                    f"Crawled {url}: {page.content_length} chars, "
                    f"{len(page.links)} links found"
                )
                return page

        except Exception as e:
            logger.error(f"Error crawling {url}: {e}")
            return None

