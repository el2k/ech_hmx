"""
Website crawling endpoints.

This module provides API endpoints for website page crawling operations.
Crawl configuration is stored in Collection.crawl_config.
"""

import fnmatch
import hashlib
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db_session_dependency
from ..logging_config import get_logger
from ..models import Collection, File as FileModel, FileDocument, WebsitePage
from ..schemas.common import ErrorResponse, PaginationMetadata
from ..schemas.websites import (
    AddPageRequest,
    AddPageResponse,
    CrawlDeeperRequest,
    CrawlDeeperResponse,
    CrawlProgressSchema,
    WebsitePageListResponse,
    WebsitePageResponse,
)

router = APIRouter()
logger = get_logger(__name__)

# Completed statuses for tree_completed calculation
COMPLETED_STATUSES = {"processed", "skipped", "failed"}
'''
这是一个基于 FastAPI + SQLAlchemy 异步架构的网站爬虫管理 API 模块，属于 RAG（检索增强生成）系统的网页采集层。它不执行真正的网页抓取，而是负责：
爬取任务的增删改查与状态管理
网站页面的父子层级关系维护（页面树）
爬取进度统计
URL 去重与深度扩展爬取
级联删除关联文件与文档数据
真正的网页抓取逻辑由 Celery 异步任务（crawl_page_task）执行，本模块只负责触发任务和管理数据。
'''
# 对 URL 做 SHA-256 哈希，用于数据库去重。
def compute_url_hash(url: str) -> str:
    """Generate SHA-256 hash of URL for deduplication."""
    return hashlib.sha256(url.encode()).hexdigest()

# 判断一个页面 + 它的所有子孙页面，是否全部进入终态。
async def check_tree_completed(
    db: AsyncSession,
    page_id: UUID,
    page_status: str,
) -> bool:
    """
    检查页面及其所有子页面是否已完成处理。
    当满足以下条件时，页面树被视为“已完成”页面本身的状态为:已处理、跳过或失败
    所有子页面(子女、孙辈等)均具有以下状态之一
    参数:
    db:数据库会话page_id:要检查的页面的UUID
    page_status:页面当前状态
    返回值:
    如果整个树已完成则为True，否则为False。
    """
    # If the page itself is not completed, the tree is not completed
    if page_status not in COMPLETED_STATUSES:
        return False

    # Use recursive CTE to find all descendant pages
    # Check if any descendant is not in completed status
    from sqlalchemy import text
    # 这里的text()用于编写原始SQL查询，因为SQLAlchemy ORM不直接支持递归CTE的复杂查询
    # 这个query将递归地查找所有子页面，并检查它们的状态是否都在COMPLETED_STATUSES中
    query = text("""
        WITH RECURSIVE descendants AS (
            -- Direct children
            SELECT id, status
            FROM rag_website_pages
            WHERE parent_page_id = :page_id

            UNION ALL

            -- Recursive: children of children
            SELECT p.id, p.status
            FROM rag_website_pages p
            INNER JOIN descendants d ON p.parent_page_id = d.id
        )
        SELECT COUNT(*) as incomplete_count
        FROM descendants
        WHERE status NOT IN ('processed', 'skipped', 'failed')
    """)

    result = await db.execute(query, {"page_id": page_id})
    row = result.fetchone()
    incomplete_count = row[0] if row else 0

    return incomplete_count == 0

# 检查树是否完成的批量函数
async def batch_check_tree_completed(
    db: AsyncSession,
    pages: List,
) -> Dict[UUID, bool]:
    """
    Batch check tree_completed status for multiple pages.

    This is more efficient than checking each page individually when
    listing multiple pages.

    Args:
        db: Database session
        pages: List of WebsitePage objects

    Returns:
        Dictionary mapping page_id to tree_completed status
    """
    if not pages:
        return {}

    result_map: Dict[UUID, bool] = {}

    # First, mark pages that are not themselves completed
    for page in pages:
        if page.status not in COMPLETED_STATUSES:
            result_map[page.id] = False

    # For pages that are completed, check their descendants
    completed_pages = [p for p in pages if p.id not in result_map]

    if not completed_pages:
        return result_map

    # Check each completed page individually using the single-page function
    # This avoids complexity with array parameters in raw SQL
    for page in completed_pages:
        tree_completed = await check_tree_completed(db, page.id, page.status)
        result_map[page.id] = tree_completed

    return result_map

# 建立页面字典的辅助函数
# 把 ORM 对象转换成标准化字典，补充 tree_completed、has_children、children 三个非数据库字段，供响应 Schema 序列化。
def _build_page_dict(
    page,
    tree_completed: bool,
    has_children: bool,
    children: Optional[List] = None,
) -> dict:
    """Build a page dictionary from a WebsitePage model."""
    return {
        "id": page.id,
        "collection_id": page.collection_id,
        "parent_page_id": page.parent_page_id,
        "url": page.url,
        "title": page.title,
        "depth": page.depth,
        "content_length": page.content_length or 0,
        "meta_description": page.meta_description,
        "status": page.status,
        "crawl_source": page.crawl_source,
        "http_status_code": page.http_status_code,
        "file_id": page.file_id,
        "discovered_links": page.discovered_links,
        "error_message": page.error_message,
        "tree_completed": tree_completed,
        "has_children": has_children,
        "children": children,
        "created_at": page.created_at,
        "updated_at": page.updated_at,
    }

# 加载子孙页面的递归函数，递归加载后代页面
async def load_descendants(
    db: AsyncSession,
    parent_ids: List[UUID],
    max_depth: int,
    current_depth: int = 0,
) -> Dict[UUID, List]:
    """
    Load descendants for a list of parent page IDs.

    Args:
        db: Database session
        parent_ids: List of parent page IDs to load children for
        max_depth: Maximum depth to load (-1 for unlimited)
        current_depth: Current recursion depth

    Returns:
        Dictionary mapping parent_page_id to list of child WebsitePage objects
    """
    if not parent_ids:
        return {}

    # Check if we've reached the depth limit
    # 一次性加载指定深度的所有后代页面，按父 ID 分组返回。
    if max_depth != -1 and current_depth >= max_depth:
        return {}

    # Load direct children
    query = select(WebsitePage).where(
        WebsitePage.parent_page_id.in_(parent_ids)
    ).order_by(WebsitePage.created_at.desc())

    result = await db.execute(query)
    children = list(result.scalars().all())

    if not children:
        return {}

    # Group children by parent
    children_by_parent: Dict[UUID, List] = {}
    for child in children:
        if child.parent_page_id not in children_by_parent:
            children_by_parent[child.parent_page_id] = []
        children_by_parent[child.parent_page_id].append(child)

    # Recursively load grandchildren if needed
    if max_depth == -1 or current_depth + 1 < max_depth:
        child_ids = [child.id for child in children]
        grandchildren_map = await load_descendants(
            db, child_ids, max_depth, current_depth + 1
        )
        # Attach grandchildren info to children
        for child in children:
            child._grandchildren = grandchildren_map.get(child.id, [])
    else:
        for child in children:
            child._grandchildren = []

    return children_by_parent

# 批量判断是否有子页面
async def batch_check_has_children(
    db: AsyncSession,
    page_ids: List[UUID],
) -> Dict[UUID, bool]:
    """
    Batch check which pages have children.

    Args:
        db: Database session
        page_ids: List of page IDs to check

    Returns:
        Dictionary mapping page_id to has_children boolean
    """
    if not page_ids:
        return {}

    # Query to find which page_ids have at least one child
    query = (
        select(WebsitePage.parent_page_id)
        .where(WebsitePage.parent_page_id.in_(page_ids))
        .distinct()
    )

    result = await db.execute(query)
    # fetchall() 指定返回所有结果行，返回的每一行是一个元组，取第一个元素即 parent_page_id
    parent_ids_with_children = {row[0] for row in result.fetchall()}

    return {page_id: page_id in parent_ids_with_children for page_id in page_ids}

# 构建完整页面树
async def build_page_tree(
    db: AsyncSession,
    pages: List,
    tree_depth: Optional[int],
    tree_completed_map: Dict[UUID, bool],
) -> List[WebsitePageResponse]:
    """
    Build a tree structure from a list of pages.

    Args:
        db: Database session
        pages: List of root-level WebsitePage objects
        tree_depth: How many levels of children to include (None/0 = none, -1 = unlimited)
        tree_completed_map: Pre-computed tree_completed values for all pages

    Returns:
        List of WebsitePageResponse with children populated
    """
    if not pages:
        return []

    # Get page IDs for has_children check
    page_ids = [page.id for page in pages]

    # If no tree depth requested, return flat list
    # # 情况1：不需要子树，返回扁平列表
    if tree_depth is None or tree_depth == 0:
        # Check which pages have children
        has_children_map = await batch_check_has_children(db, page_ids)

        return [
            WebsitePageResponse(**_build_page_dict(
                page,
                tree_completed_map.get(page.id, False),
                has_children_map.get(page.id, False),
                children=None
            ))
            for page in pages
        ]

    # Load descendants
    # 情况2：需要子树，先加载所有后代 
    children_map = await load_descendants(db, page_ids, tree_depth, 0)

    # Collect all loaded pages for tree_completed and has_children calculation
    #  # 收集所有后代页面，批量计算状态
    all_descendant_pages = []
    all_descendant_ids = []
    # # 批量计算所有页面的 tree_completed 和 has_children
    def collect_descendants(children_by_parent: Dict[UUID, List]):
        for children_list in children_by_parent.values():
            for child in children_list:
                all_descendant_pages.append(child)
                all_descendant_ids.append(child.id)
                if hasattr(child, '_grandchildren') and child._grandchildren:
                    # Recursively collect from grandchildren
                    gc_map = {child.id: child._grandchildren}
                    collect_descendants(gc_map)

    collect_descendants(children_map)

    # Calculate tree_completed for all descendant pages
    descendant_tree_completed = await batch_check_tree_completed(db, all_descendant_pages)

    # Calculate has_children for all pages (root + descendants)
    all_page_ids = page_ids + all_descendant_ids
    has_children_map = await batch_check_has_children(db, all_page_ids)

    # Merge with the original map
    full_tree_completed_map = {**tree_completed_map, **descendant_tree_completed}
    # 递归构建响应树
    def build_response_tree(page) -> WebsitePageResponse:
        """Recursively build response tree for a page."""
        children_list = children_map.get(page.id, [])
        has_children = has_children_map.get(page.id, False)

        if not children_list:
            return WebsitePageResponse(**_build_page_dict(
                page,
                full_tree_completed_map.get(page.id, False),
                has_children,
                children=[]
            ))

        # Build children recursively
        child_responses = []
        for child in children_list:
            # Get grandchildren from the attached attribute
            grandchildren = getattr(child, '_grandchildren', [])
            if grandchildren:
                # Temporarily update children_map for recursive call
                children_map[child.id] = grandchildren
            child_responses.append(build_response_tree(child))

        return WebsitePageResponse(**_build_page_dict(
            page,
            full_tree_completed_map.get(page.id, False),
            has_children,
            children=child_responses
        ))

    return [build_response_tree(page) for page in pages]

# URL 存在性检查（去重）
async def check_url_exists_in_collection(
    db: AsyncSession,
    collection_id: UUID,
    url_hash: str,
) -> Tuple[bool, Optional[str]]:
    """
    Check if a URL already exists in the collection's pages.

    Returns:
        Tuple of (exists: bool, status: Optional[str])
        - If exists=True, status contains the current page status
        - If exists=False, status is None
    """
    query = select(WebsitePage.status).where(
        and_(
            WebsitePage.collection_id == collection_id,
            WebsitePage.url_hash == url_hash,
        )
    )
    result = await db.execute(query)
    page_status = result.scalar_one_or_none()

    if page_status is not None:
        return (True, page_status)
    return (False, None)


async def check_urls_exist_in_collection(
    db: AsyncSession,
    collection_id: UUID,
    url_hashes: List[str],
) -> set:
    """
    Check which URLs already exist in the collection's pages.

    Returns:
        Set of url_hashes that already exist
    """
    if not url_hashes:
        return set()

    query = select(WebsitePage.url_hash).where(
        and_(
            WebsitePage.collection_id == collection_id,
            WebsitePage.url_hash.in_(url_hashes),
        )
    )
    result = await db.execute(query)
    existing_hashes = {row[0] for row in result.fetchall()}
    return existing_hashes

# 爬取进度计算
async def _build_progress(db: AsyncSession, collection_id: UUID) -> CrawlProgressSchema:
    """Build progress schema by querying page statuses."""
    # Count pages by status
    # # 按状态分组统计数量
    query = select(
        WebsitePage.status,
        func.count(WebsitePage.id)
    ).where(
        WebsitePage.collection_id == collection_id
    ).group_by(WebsitePage.status)

    result = await db.execute(query)
    status_counts = dict(result.fetchall())

    total = sum(status_counts.values())
    pending = status_counts.get("pending", 0) + status_counts.get("crawling", 0)
    crawled = status_counts.get("fetched", 0) + status_counts.get("extracted", 0)
    processed = status_counts.get("processed", 0)
    skipped = status_counts.get("skipped", 0)
    failed = status_counts.get("failed", 0)
    processing = status_counts.get("processing", 0)

    # Include skipped pages in progress since they are completed work
    # (URLs intentionally not crawled due to exclude patterns, depth limits, etc.)
    completed = crawled + processed + skipped + failed
    progress_percent = (completed / total * 100) if total > 0 else 0

    return CrawlProgressSchema(
        total_pages=total,
        pages_pending=pending,
        pages_processing=processing,
        pages_crawled=crawled + processed + skipped,  # Include skipped as "crawled" (completed)
        pages_processed=processed + skipped,  # Skipped pages count as processed (no further work needed)
        pages_failed=failed,
        progress_percent=min(progress_percent, 100.0),
    )

# 级联删除页面
async def _delete_file_and_documents(
    db: AsyncSession,
    file_id: UUID,
) -> Optional[str]:
    """
    Delete a File and all its associated FileDocument records.

    Args:
        db: Database session
        file_id: UUID of the file to delete

    Returns:
        Storage path of the deleted file (for physical file cleanup), or None if file not found
    """
    # Get file record
     # 1. 查文件记录，拿到物理路径
    # 2. 先删关联的 FileDocument（文档切片）
    # 3. 再删 File 记录
    # 4. 返回物理文件路径

    #   级联删除页面
    file_query = select(FileModel).where(FileModel.id == file_id)
    file_result = await db.execute(file_query)
    file_record = file_result.scalar_one_or_none()

    if not file_record:
        return None

    storage_path = file_record.storage_path

    # Delete associated FileDocument records first
    await db.execute(
        delete(FileDocument).where(FileDocument.file_id == file_id)
    )
    logger.debug(f"Deleted FileDocument records for file {file_id}")

    # Delete the file record
    await db.delete(file_record)
    logger.debug(f"Deleted file record {file_id}")

    return storage_path


async def _delete_page_cascade(
    db: AsyncSession,
    page: WebsitePage,
) -> None:
    """
    Delete a WebsitePage and its associated File/FileDocument records.

    Args:
        db: Database session
        page: WebsitePage to delete
    """
    storage_path = None

    # Delete associated file if exists
    if page.file_id:
        storage_path = await _delete_file_and_documents(db, page.file_id)

    # Delete the page
    await db.delete(page)

    # Delete physical file from storage after DB changes
     # 数据库提交后删物理文件
    if storage_path and os.path.exists(storage_path):
        try:
            os.remove(storage_path)
            logger.debug(f"Deleted physical file from storage: {storage_path}")
        except Exception as e:
            logger.warning(f"Failed to delete physical file {storage_path}: {e}")


# ============================================================================
# Page List Endpoints
# ============================================================================
# 分页查询集合内的页面，支持状态 / 深度 / 父页面过滤，支持树形结构返回。
@router.get(
    "/pages",
    response_model=WebsitePageListResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Collection not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def list_pages(
    collection_id: UUID = Query(..., description="Collection ID"),
    status: Optional[str] = Query(None, description="Filter by page status"),
    depth: Optional[int] = Query(None, description="Filter by depth"),
    parent_page_id: Optional[UUID] = Query(None, description="Filter by parent page ID"),
    tree_depth: Optional[int] = Query(
        None,
        ge=-1,
        le=10,
        description="Number of child levels to include. 0/None=no children, 1=direct children, -1=unlimited",
    ),
    limit: int = Query(20, ge=1, le=100, description="Number of pages to return"),
    offset: int = Query(0, ge=0, description="Number of pages to skip"),
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db_session_dependency),
):
    """
    List all pages in a collection.

    When tree_depth is specified, the response includes child pages in a hierarchical structure.
    - tree_depth=0 or None: Flat list (no children)
    - tree_depth=1: Include direct children only
    - tree_depth=2: Include children and grandchildren
    - tree_depth=-1: Include all descendants (unlimited depth)

    When no parent_page_id filter is specified and tree_depth > 0, returns root pages
    (where parent_page_id IS NULL) with their children.
    """
    # Verify collection exists
    coll_query = select(Collection).where(
        and_(
            Collection.id == collection_id,
            Collection.project_id == project_id,
            Collection.deleted_at.is_(None),
        )
    )
    coll_result = await db.execute(coll_query)
    if not coll_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Collection not found")

    # Query pages
    query = select(WebsitePage).where(WebsitePage.collection_id == collection_id)

    if status:
        query = query.where(WebsitePage.status == status)
    if depth is not None:
        query = query.where(WebsitePage.depth == depth)

    # Handle parent_page_id filtering
    # When tree_depth > 0 and no parent_page_id specified, default to root pages
    if parent_page_id is not None:
        query = query.where(WebsitePage.parent_page_id == parent_page_id)
    elif tree_depth is not None and tree_depth != 0:
        # Default to root pages when building tree without explicit parent filter
        query = query.where(WebsitePage.parent_page_id.is_(None))

    # Get total count (only counts root-level pages in tree mode)
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Apply pagination
    query = query.offset(offset).limit(limit).order_by(WebsitePage.created_at.desc())

    result = await db.execute(query)
    pages = list(result.scalars().all())

    # Batch calculate tree_completed for root pages
    tree_completed_map = await batch_check_tree_completed(db, pages)

    # Build response with tree structure if tree_depth is specified
    page_responses = await build_page_tree(db, pages, tree_depth, tree_completed_map)

    pagination = PaginationMetadata(
        total=total,
        limit=limit,
        offset=offset,
        has_next=offset + limit < total,
        has_prev=offset > 0,
    )

    return WebsitePageListResponse(data=page_responses, pagination=pagination)

# 单页详情，校验页面存在 → 计算 tree_completed 和 has_children → 构建响应返回。
@router.get(
    "/pages/{page_id}",
    response_model=WebsitePageResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Page not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_page(
    page_id: UUID,
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db_session_dependency),
):
    """
    Get details of a specific page.
    """
    query = select(WebsitePage).where(
        and_(
            WebsitePage.id == page_id,
            WebsitePage.project_id == project_id,
        )
    )

    result = await db.execute(query)
    page = result.scalar_one_or_none()

    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    # Calculate tree_completed and has_children for this page
    tree_completed = await check_tree_completed(db, page.id, page.status)
    has_children_map = await batch_check_has_children(db, [page.id])
    has_children = has_children_map.get(page.id, False)

    # Build response
    return WebsitePageResponse(**_build_page_dict(
        page,
        tree_completed,
        has_children,
        children=None
    ))


# ============================================================================
# Add Page Endpoints
# ============================================================================
# 新增爬取页面
'''校验集合存在性
计算 URL 哈希，检查是否已存在：
正在爬取中：返回「正在爬取」提示
已存在：返回「已存在」提示
校验父页面（如果指定），计算新页面深度 = 父页面深度 + 1
如果请求携带爬取配置（包含 / 排除规则、最大深度），更新集合的 crawl_config
创建 WebsitePage 记录，状态设为 pending，来源标记为 manual
提交数据库'''
@router.post(
    "/pages",
    response_model=AddPageResponse,
    status_code=201,
    responses={
        404: {"model": ErrorResponse, "description": "Collection not found"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def add_page(
    request: AddPageRequest,
    collection_id: UUID = Query(..., description="Target collection ID"),
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db_session_dependency),
):
    """
    Add a page to crawl in a collection.

    This will create a page record and trigger crawling.
    If max_depth > 0, discovered links will also be crawled.

    Deduplication:
    - If the URL already exists in the collection, it will be skipped
    """
    # Verify collection exists and belongs to project
    coll_query = select(Collection).where(
        and_(
            Collection.id == collection_id,
            Collection.project_id == project_id,
            Collection.deleted_at.is_(None),
        )
    )
    coll_result = await db.execute(coll_query)
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    url = str(request.url)
    url_hash = compute_url_hash(url)

    # Check if URL already exists in collection
    exists, existing_status = await check_url_exists_in_collection(
        db, collection_id, url_hash
    )

    if exists:
        if existing_status in ("pending", "crawling", "fetched"):
            return AddPageResponse(
                success=False,
                page_id=None,
                message=f"URL is currently being crawled (status: {existing_status})",
                status="crawling",
            )
        else:
            return AddPageResponse(
                success=False,
                page_id=None,
                message=f"URL already exists in collection (status: {existing_status})",
                status="exists",
            )

    # Validate parent page if provided
    parent_page = None
    page_depth = 0
    if request.parent_page_id:
        parent_query = select(WebsitePage).where(
            and_(
                WebsitePage.id == request.parent_page_id,
                WebsitePage.collection_id == collection_id,
            )
        )
        parent_result = await db.execute(parent_query)
        parent_page = parent_result.scalar_one_or_none()

        if not parent_page:
            raise HTTPException(
                status_code=400,
                detail="Parent page not found in this collection"
            )

        page_depth = parent_page.depth + 1

    # Update collection crawl_config if options provided
    if request.options or request.include_patterns or request.exclude_patterns:
        crawl_config = collection.crawl_config or {}
        if request.options:
            crawl_config.update(request.options.model_dump(exclude_none=True))
        if request.include_patterns:
            crawl_config["include_patterns"] = request.include_patterns
        if request.exclude_patterns:
            crawl_config["exclude_patterns"] = request.exclude_patterns
        if request.max_depth:
            crawl_config["max_depth"] = request.max_depth
        collection.crawl_config = crawl_config

    # Create new page record
    new_page = WebsitePage(
        collection_id=collection_id,
        project_id=project_id,
        parent_page_id=request.parent_page_id,
        url=url,
        url_hash=url_hash,
        depth=page_depth,
        status="pending",
        crawl_source="manual",
        content_length=0,
    )

    db.add(new_page)
    await db.commit()
    await db.refresh(new_page)

    logger.info(f"Added page {url} to collection {collection_id}")

    # Trigger crawl task
    from ..tasks.website_crawling import crawl_page_task
    try:
        
        # 触发 Celery 异步任务,真正的网页抓取、内容提取在后台任务中执行
        task = crawl_page_task.delay(
            str(new_page.id),
            auto_discover=(request.max_depth > 0),
            max_depth=request.max_depth,
        )
        logger.info(f"Triggered crawl page task {task.id} for page {new_page.id}")
    except Exception as e:
        logger.warning(f"Failed to trigger crawl task: {e}")

    return AddPageResponse(
        success=True,
        page_id=new_page.id,
        message="Page added to crawl queue successfully",
        status="added",
    )
# DELETE /pages/{page_id} —— 删除页面
@router.delete(
    "/pages/{page_id}",
    status_code=204,
    responses={
        404: {"model": ErrorResponse, "description": "Page not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def delete_page(
    page_id: UUID,
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db_session_dependency),
):
    """
    Delete a page from the collection.

    This performs a hard delete that also removes:
    - Associated File record (if any)
    - Associated FileDocument records (if any)
    - Physical file from storage (if any)
    """
    query = select(WebsitePage).where(
        and_(
            WebsitePage.id == page_id,
            WebsitePage.project_id == project_id,
        )
    )

    result = await db.execute(query)
    page = result.scalar_one_or_none()

    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    # Delete page with cascade (File, FileDocument, physical file)
    await _delete_page_cascade(db, page)
    await db.commit()

    logger.info(f"Deleted page {page_id} with associated files")

# POST /pages/{page_id}/recrawl —— 重新爬取
@router.post(
    "/pages/{page_id}/recrawl",
    response_model=AddPageResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Page not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def recrawl_page(
    page_id: UUID,
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db_session_dependency),
):
    """
    Trigger re-crawling of an existing page.
    """
    query = select(WebsitePage).where(
        and_(
            WebsitePage.id == page_id,
            WebsitePage.project_id == project_id,
        )
    )

    result = await db.execute(query)
    page = result.scalar_one_or_none()

    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    # Reset page status
    page.status = "pending"
    page.error_message = None
    await db.commit()

    # Trigger crawl task
    from ..tasks.website_crawling import crawl_page_task
    try:
        task = crawl_page_task.delay(str(page_id), auto_discover=False)
        logger.info(f"Triggered recrawl task {task.id} for page {page_id}")
    except Exception as e:
        logger.warning(f"Failed to trigger recrawl task: {e}")

    return AddPageResponse(
        success=True,
        page_id=page_id,
        message="Page queued for re-crawling",
        status="added",
    )


# ============================================================================
# Progress Endpoint
# ============================================================================
# GET /progress —— 爬取进度
@router.get(
    "/progress",
    response_model=CrawlProgressSchema,
    responses={
        404: {"model": ErrorResponse, "description": "Collection not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
async def get_crawl_progress(
    collection_id: UUID = Query(..., description="Collection ID"),
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db_session_dependency),
):
    """
    Get crawl progress for a collection.
    """
    # Verify collection exists
    coll_query = select(Collection).where(
        and_(
            Collection.id == collection_id,
            Collection.project_id == project_id,
            Collection.deleted_at.is_(None),
        )
    )
    coll_result = await db.execute(coll_query)
    if not coll_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Collection not found")

    return await _build_progress(db, collection_id)


@router.post(
    "/pages/{page_id}/crawl-deeper",
    response_model=CrawlDeeperResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Page not found"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Internal server error"},
    },
)
# POST /pages/{page_id}/crawl-deeper —— 深度扩展爬取
# 这是最复杂的接口，功能是：从一个已爬取的页面中提取所有链接，批量加入爬取队列，实现层级深度扩散。
async def crawl_deeper_from_page(
    page_id: UUID,
    request: CrawlDeeperRequest,
    project_id: UUID = Query(..., description="Project ID"),
    db: AsyncSession = Depends(get_db_session_dependency),
):
    """
    Extract links from an existing page and add them to the crawl queue.

    This endpoint allows deep crawling from a specific page that has already
    been crawled. It extracts all links from the page's content and adds
    new URLs to the crawl queue.

    Deduplication rules:
    - URLs already in the collection are skipped
    - URLs currently being crawled are skipped
    - New pages have depth = source_page.depth + 1
    - Pages exceeding max_depth are not added
    """
    ''' 校验：查源页面、查所属集合
        前置判断：
            页面没有内容也没有发现的链接 → 直接返回
            新深度超过最大允许深度 → 直接返回
        多源提取链接：
            优先用 discovered_links（爬取工具 crawl4ai 返回的结构化链接）
            没有则用正则从 Markdown 内容中提取 HTML href 和 Markdown 链接
            再从 page_metadata 元数据中补充链接
        链接清洗过滤：
            normalize_url：相对路径转绝对路径、去掉锚点、过滤非 http 链接、只保留同域名
            should_crawl：用 fnmatch 通配符匹配包含 / 排除规则（优先用请求参数，其次用集合配置）
        去重：先本地去重，再批量查数据库过滤已存在的 URL
        批量创建页面：
            每个新页面父 ID 为当前页，深度 +1，来源标记为 deep_crawl
            把本次深度爬取的自定义配置（最大深度、规则）存到页面的 crawl_config 中，覆盖集合级配置
            批量触发任务：给每个新页面触发异步爬取任务，开启自动发现
            返回统计结果：新增数、跳过数、发现链接总数、新增 URL 列表'''
    # Get the source page
    # page_query: 查询源页面，确保它属于指定项目 
    page_query = select(WebsitePage).where(
        and_(
            WebsitePage.id == page_id,
            WebsitePage.project_id == project_id,
        )
    )
    page_result = await db.execute(page_query)
    source_page = page_result.scalar_one_or_none()

    if not source_page:
        raise HTTPException(status_code=404, detail="Page not found")

    # Get collection for configuration
    # coll_query: 查询源页面所属的集合，获取爬取配置
    coll_query = select(Collection).where(Collection.id == source_page.collection_id)
    coll_result = await db.execute(coll_query)
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Get crawl config from collection
    crawl_config = collection.crawl_config or {}

    # Check if page has content or discovered_links
    # has_discovered_links: 判断源页面是否有已发现的链接
    has_discovered_links = source_page.discovered_links and len(source_page.discovered_links) > 0
    if not source_page.content_markdown and not has_discovered_links:
        return CrawlDeeperResponse(
            success=True,
            source_page_id=page_id,
            pages_added=0,
            pages_skipped=0,
            links_found=0,
            # 页面没有内容也没有发现的链接，无法提取
            message="Page has no content or discovered links to extract from",
            added_urls=[],
        )

    # Calculate new depth and check max_depth limit
    new_depth = source_page.depth + 1
    max_allowed_depth = source_page.depth + request.max_depth

    if new_depth > max_allowed_depth:
        return CrawlDeeperResponse(
            success=True,
            source_page_id=page_id,
            pages_added=0,
            pages_skipped=0,
            links_found=0,
            message="Max depth reached, no pages added",
            added_urls=[],
        )

    # Extract links from discovered_links or content
    # Parse base domain from source page URL
    # urlparse: 解析源页面 URL，获取域名，用于后续过滤同域链接
    parsed_source = urlparse(source_page.url)
    base_domain = parsed_source.netloc

    raw_links = set()

    # First, use discovered_links if available (from crawl4ai)
    # 首先，优先使用 discovered_links（结构化链接）提取
    if source_page.discovered_links:
        for link_info in source_page.discovered_links:
            if isinstance(link_info, dict):
                raw_links.add(link_info.get("url", ""))
            elif isinstance(link_info, str):
                raw_links.add(link_info)

    # If no discovered_links, extract from content
    # 如果没有 discovered_links，则从内容中提取
    if not raw_links and source_page.content_markdown:
        # Simple regex for href extraction
        # href_pattern: 用正则匹配 HTML href 属性
        href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
        # Also look for markdown links
        # 也看看 Markdown 链接格式 [text](url)
        md_link_pattern = re.compile(r'\[([^\]]*)\]\(([^)]+)\)', re.IGNORECASE)

        # Extract from HTML-style hrefs (if any HTML remnants)
        # 提取 HTML href 链接
        for match in href_pattern.finditer(source_page.content_markdown):
            raw_links.add(match.group(1))

        # Extract from markdown links
        # 提取 Markdown 链接
        for match in md_link_pattern.finditer(source_page.content_markdown):
            raw_links.add(match.group(2))

    # Also check page_metadata for stored links
    # 也检查 page_metadata 中的 links 字段
    if source_page.page_metadata and "links" in source_page.page_metadata:
        for link in source_page.page_metadata.get("links", []):
            if isinstance(link, str):
                raw_links.add(link)
            elif isinstance(link, dict):
                raw_links.add(link.get("href", ""))

    # Normalize and filter links
    # 标准化 URL，过滤非 http 链接、去掉锚点、只保留同域名
    def normalize_url(url: str, base_url: str) -> Optional[str]:
        """Normalize and validate URL."""
        try:
            if not url or url.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                return None

            # Handle relative URLs
            if not url.startswith(('http://', 'https://')):
                url = urljoin(base_url, url)

            parsed = urlparse(url)

            # Remove fragments
            url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if parsed.query:
                url += f"?{parsed.query}"

            # Only allow same domain
            if parsed.netloc != base_domain:
                return None

            return url
        except Exception:
            return None
    # should_crawl: 检查 URL 是否匹配包含/排除规则
    def should_crawl(url: str) -> bool:
        """Check if URL matches include/exclude patterns."""
        # Use request patterns if provided, otherwise use collection config
        exclude_patterns = request.exclude_patterns or crawl_config.get("exclude_patterns", [])
        include_patterns = request.include_patterns or crawl_config.get("include_patterns", [])

        for pattern in exclude_patterns:
            if fnmatch.fnmatch(url, pattern):
                return False

        if include_patterns:
            return any(fnmatch.fnmatch(url, p) for p in include_patterns)

        return True

    # Process and filter links
    # 得到有效链接列表，去重，过滤已存在的 URL
    valid_links = []
    for link in raw_links:
        normalized = normalize_url(link, source_page.url)
        if normalized and should_crawl(normalized):
            valid_links.append(normalized)

    valid_links = list(set(valid_links))  # Deduplicate
    links_found = len(valid_links)

    if not valid_links:
        return CrawlDeeperResponse(
            success=True,
            source_page_id=page_id,
            pages_added=0,
            pages_skipped=0,
            links_found=0,
            message="No valid links found in page",
            added_urls=[],
        )

    # Check which URLs already exist in collection
    url_to_hash = {url: compute_url_hash(url) for url in valid_links}
    existing_hashes = await check_urls_exist_in_collection(
        db, source_page.collection_id, list(url_to_hash.values())
    )

    # Filter out existing URLs
    new_urls = [url for url, h in url_to_hash.items() if h not in existing_hashes]
    skipped_count = len(valid_links) - len(new_urls)

    if not new_urls:
        return CrawlDeeperResponse(
            success=True,
            source_page_id=page_id,
            pages_added=0,
            pages_skipped=skipped_count,
            links_found=links_found,
            message="All discovered links already exist in collection",
            added_urls=[],
        )

    # Build page-level crawl config to override collection's max_depth
    # This ensures the deep crawl can go beyond the collection's original max_depth limit
    page_crawl_config = {
        "max_depth": max_allowed_depth,  # Absolute depth limit for this deep crawl
    }
    # Include any request-level pattern overrides
    if request.exclude_patterns:
        page_crawl_config["exclude_patterns"] = request.exclude_patterns
    if request.include_patterns:
        page_crawl_config["include_patterns"] = request.include_patterns

    # Add new pages to the crawl queue and trigger crawl tasks
    added_urls = []
    added_page_ids = []
    # 这里批量创建新页面记录，父页面为当前页，深度 +1，来源标记为 deep_crawl
    for url in new_urls:
        new_page = WebsitePage(
            collection_id=source_page.collection_id,
            project_id=project_id,
            parent_page_id=page_id,  # Set parent page
            url=url,
            url_hash=url_to_hash[url],
            depth=new_depth,
            status="pending",
            crawl_source="deep_crawl",  # Mark as deep crawl
            content_length=0,
            crawl_config=page_crawl_config,  # Store max_depth override in page config
        )
        db.add(new_page)
        await db.flush()  # Get the ID
        added_urls.append(url)
        added_page_ids.append(new_page.id)

    await db.commit()

    logger.info(
        f"Added {len(added_urls)} pages from deep crawl of page {page_id}, "
        f"skipped {skipped_count} existing URLs, max_allowed_depth={max_allowed_depth}"
    )

    # Trigger crawl tasks for each new page
    from ..tasks.website_crawling import crawl_page_task
    # 这里批量触发异步爬取任务，开启自动发现，crawl_page_task 会在后台执行真正的网页抓取和内容提取
    for new_page_id in added_page_ids:
        try:
            task = crawl_page_task.delay(
                str(new_page_id),
                auto_discover=True,
                max_depth=max_allowed_depth,
            )
            logger.debug(f"Triggered crawl page task {task.id} for page {new_page_id}")
        except Exception as e:
            logger.warning(f"Failed to trigger crawl task for page {new_page_id}: {e}")

    return CrawlDeeperResponse(
        success=True,
        source_page_id=page_id,
        pages_added=len(added_urls),
        pages_skipped=skipped_count,
        links_found=links_found,
        message=f"Added {len(added_urls)} new pages to crawl queue",
        added_urls=added_urls,
    )

