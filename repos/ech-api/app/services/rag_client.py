# =============================================================================
# 模块：RAG 服务客户端 (RAG Service Client)
# =============================================================================
# 该模块提供了与外部 RAG (Retrieval-Augmented Generation) 服务通信的 HTTP 客户端，
# 主要包括：
# 1. 集合管理（列表、创建、获取、更新、删除）
# 2. 文件管理（列表、上传、下载、删除、批量上传）
# 3. 网页爬取管理（列表页面、添加、删除、重新爬取、深度爬取）
# 4. QA 对管理（创建、列表、批量创建、导入、更新、删除）
# 5. 文档搜索
# 
# 设计目的：
# - 封装与 RAG 服务的 HTTP 通信细节
# - 提供统一的接口供其他模块调用
# - 处理错误、超时和日志记录
# - 支持文件上传和下载的流式传输
# 
# 依赖服务：外部 RAG 服务
# =============================================================================

import json
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

import httpx
from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("rag_client")


# =============================================================================
# RAG 服务客户端类
# =============================================================================

class RAGServiceClient:
    """
    HTTP 客户端，用于与外部 RAG 服务通信。

    功能分组：
    1. 集合管理：CRUD 操作
    2. 文件管理：上传、下载、删除、批量操作
    3. 网页爬取：页面管理、爬取控制
    4. QA 对管理：创建、列表、批量创建、导入

    配置来源：
    - base_url: 从环境变量 RAG_SERVICE_URL 读取
    - timeout: 从环境变量 RAG_SERVICE_TIMEOUT 读取
    - api_key: 从环境变量 RAG_SERVICE_API_KEY 读取（当前未使用）
    """

    def __init__(self):
        """初始化 RAG 服务客户端。"""
        self.base_url = settings.RAG_SERVICE_URL.rstrip("/")
        self.timeout = settings.RAG_SERVICE_TIMEOUT
        self.api_key = settings.RAG_SERVICE_API_KEY

    # =========================================================================
    # 请求头配置
    # =========================================================================

    def _get_headers(self) -> Dict[str, str]:
        """
        获取 RAG 服务请求的请求头（JSON 请求）。

        Returns:
            Dict[str, str]: 请求头字典
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "TGO-API-Service/0.1.0",
        }
        return headers

    def _get_multipart_headers(self) -> Dict[str, str]:
        """
        获取 RAG 服务请求的请求头（Multipart 请求）。

        用于文件上传等需要 multipart/form-data 的场景。

        Returns:
            Dict[str, str]: 请求头字典
        """
        headers = {
            "User-Agent": "TGO-API-Service/0.1.0",
        }
        return headers

    # =========================================================================
    # HTTP 请求核心方法
    # =========================================================================

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """
        向 RAG 服务发起 HTTP 请求的核心方法。

        执行流程：
        1. 构建完整 URL
        2. 生成请求 ID 用于追踪
        3. 根据请求类型选择请求头
        4. 发起异步 HTTP 请求
        5. 记录请求和响应日志
        6. 处理超时和连接错误

        Args:
            method: HTTP 方法
            endpoint: API 端点路径
            json_data: JSON 请求体
            params: URL 查询参数
            files: 文件上传数据
            data: 表单数据

        Returns:
            httpx.Response: HTTP 响应对象

        Raises:
            HTTPException: 超时（504）或连接失败（502）
        """
        url = f"{self.base_url}{endpoint}"
        request_id = str(uuid4())

        # 根据请求类型选择合适的请求头
        if files:
            headers = self._get_multipart_headers()
        else:
            headers = self._get_headers()

        headers["X-Request-ID"] = request_id

        logger.info(
            f"RAG service request: {method} {url}",
            extra={
                "request_id": request_id,
                "method": method,
                "url": url,
                "has_files": bool(files),
                "params": params,
            }
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    params=params,
                    files=files,
                    data=data,
                )

                logger.info(
                    f"RAG service response: {response.status_code}",
                    extra={
                        "request_id": request_id,
                        "status_code": response.status_code,
                        "response_time": response.elapsed.total_seconds() if response.elapsed else None,
                    }
                )

                return response

        except httpx.TimeoutException as e:
            logger.error(
                f"RAG service timeout: {url}",
                extra={"request_id": request_id, "timeout": self.timeout}
            )
            raise HTTPException(
                status_code=504,
                detail="RAG service request timed out"
            )
        except httpx.RequestError as e:
            logger.error(
                f"RAG service request error: {e}",
                extra={"request_id": request_id, "error": str(e)}
            )
            raise HTTPException(
                status_code=502,
                detail="Failed to connect to RAG service"
            )

    async def _handle_response(self, response: httpx.Response) -> Any:
        """
        处理 RAG 服务响应并转换错误。

        执行流程：
        1. 如果响应成功（2xx），解析 JSON 或返回文本
        2. 如果响应是 204 No Content，返回 None
        3. 如果响应是错误（4xx/5xx），解析错误信息并抛出 HTTPException

        Args:
            response: HTTP 响应对象

        Returns:
            Any: 解析后的响应数据（JSON 或文本）

        Raises:
            HTTPException: 包含错误详情
        """
        if response.is_success:
            if response.status_code == 204:
                return None
            try:
                return response.json()
            except json.JSONDecodeError:
                return response.text

        # 处理错误响应
        try:
            error_data = response.json()
        except json.JSONDecodeError:
            error_data = {"error": {"message": response.text or "Unknown error"}}

        logger.warning(
            f"RAG service error response: {response.status_code}",
            extra={
                "status_code": response.status_code,
                "error_data": error_data,
            }
        )

        raise HTTPException(
            status_code=response.status_code,
            detail=error_data
        )

    # =========================================================================
    # 1. 集合管理 (Collection Management)
    # =========================================================================

    async def list_collections(
        self,
        project_id: str,
        display_name: Optional[str] = None,
        collection_type: Optional[str] = None,
        tags: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        从 RAG 服务获取集合列表。

        Args:
            project_id: 项目 ID
            display_name: 显示名称过滤（可选）
            collection_type: 集合类型过滤（可选）
            tags: 标签过滤（可选）
            limit: 每页数量
            offset: 分页偏移量

        Returns:
            Dict[str, Any]: 集合列表响应
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if display_name:
            params["display_name"] = display_name
        if collection_type:
            params["collection_type"] = collection_type
        if tags:
            params["tags"] = tags
        params["project_id"] = project_id

        response = await self._make_request(
            "GET", "/v1/collections", params=params
        )
        result = await self._handle_response(response)

        # 转换分页字段名以保持与我们的 schema 一致
        if isinstance(result, dict) and "pagination" in result:
            pagination = result["pagination"]
            if "has_previous" in pagination:
                pagination["has_prev"] = pagination.pop("has_previous")

        return result

    async def create_collection(
        self,
        project_id: str,
        collection_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        在 RAG 服务中创建集合。

        Args:
            project_id: 项目 ID
            collection_data: 集合配置数据

        Returns:
            Dict[str, Any]: 创建的集合信息
        """
        response = await self._make_request(
            "POST", "/v1/collections", json_data=collection_data, params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def get_collection(
        self,
        project_id: str,
        collection_id: str,
        include_stats: bool = False,
    ) -> Dict[str, Any]:
        """
        从 RAG 服务获取集合详情。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            include_stats: 是否包含统计信息

        Returns:
            Dict[str, Any]: 集合详情
        """
        params = {"include_stats": include_stats, "project_id": project_id}
        response = await self._make_request(
            "GET", f"/v1/collections/{collection_id}", params=params
        )
        return await self._handle_response(response)

    async def update_collection(
        self,
        project_id: str,
        collection_id: str,
        collection_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        更新 RAG 服务中的集合。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            collection_data: 更新数据

        Returns:
            Dict[str, Any]: 更新后的集合信息
        """
        response = await self._make_request(
            "PUT", f"/v1/collections/{collection_id}", json_data=collection_data, params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def delete_collection(
        self,
        project_id: str,
        collection_id: str,
    ) -> None:
        """
        从 RAG 服务删除集合。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
        """
        response = await self._make_request(
            "DELETE", f"/v1/collections/{collection_id}", params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def search_collection_documents(
        self,
        project_id: str,
        collection_id: str,
        search_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        在集合中搜索文档。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            search_data: 搜索参数（包含查询文本、top_k 等）

        Returns:
            Dict[str, Any]: 搜索结果
        """
        response = await self._make_request(
            "POST", f"/v1/collections/{collection_id}/documents/search",
            json_data=search_data, params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def list_collection_pages(
        self,
        project_id: str,
        collection_id: str,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        列出网站集合的已爬取页面。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            status: 页面状态过滤（pending/crawling/done/error）
            limit: 每页数量
            offset: 分页偏移量

        Returns:
            Dict[str, Any]: 页面列表响应
        """
        params: Dict[str, Any] = {
            "project_id": project_id,
            "limit": limit,
            "offset": offset,
        }
        if status:
            params["status"] = status

        response = await self._make_request(
            "GET", f"/v1/collections/{collection_id}/pages", params=params
        )
        result = await self._handle_response(response)

        # 转换分页字段名以保持一致性
        if isinstance(result, dict) and "pagination" in result:
            pagination = result["pagination"]
            if "has_previous" in pagination:
                pagination["has_prev"] = pagination.pop("has_previous")

        return result

    # =========================================================================
    # 2. 文件管理 (File Management)
    # =========================================================================

    async def list_files(
        self,
        project_id: str,
        collection_id: Optional[str] = None,
        status: Optional[str] = None,
        content_type: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        tags: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        从 RAG 服务获取文件列表。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID 过滤（可选）
            status: 状态过滤（可选）
            content_type: 内容类型过滤（可选）
            uploaded_by: 上传者过滤（可选）
            tags: 标签过滤（可选）
            limit: 每页数量
            offset: 分页偏移量

        Returns:
            Dict[str, Any]: 文件列表响应
        """
        params = {"limit": limit, "offset": offset}
        if collection_id:
            params["collection_id"] = collection_id
        if status:
            params["status"] = status
        if content_type:
            params["content_type"] = content_type
        if uploaded_by:
            params["uploaded_by"] = uploaded_by
        if tags:
            params["tags"] = tags
        params["project_id"] = project_id

        response = await self._make_request(
            "GET", "/v1/files", params=params
        )
        result = await self._handle_response(response)

        # 转换分页字段名以保持一致性
        if isinstance(result, dict) and "pagination" in result:
            pagination = result["pagination"]
            if "has_previous" in pagination:
                pagination["has_prev"] = pagination.pop("has_previous")

        return result

    async def upload_file(
        self,
        project_id: str,
        file: UploadFile,
        collection_id: Optional[str] = None,
        description: Optional[str] = None,
        language: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        向 RAG 服务上传文件。

        Args:
            project_id: 项目 ID
            file: 要上传的文件
            collection_id: 目标集合 ID（可选）
            description: 文件描述
            language: 文件语言
            tags: 标签

        Returns:
            Dict[str, Any]: 上传结果（包含文件 ID）
        """
        files = {"file": (file.filename, file.file, file.content_type)}
        data = {"project_id": project_id}

        if collection_id:
            data["collection_id"] = collection_id
        if description:
            data["description"] = description
        if language:
            data["language"] = language
        if tags:
            data["tags"] = tags

        response = await self._make_request(
            "POST", "/v1/files", files=files, data=data
        )
        return await self._handle_response(response)

    async def get_file(
        self,
        project_id: str,
        file_id: str,
    ) -> Dict[str, Any]:
        """
        从 RAG 服务获取文件详情。

        Args:
            project_id: 项目 ID
            file_id: 文件 ID

        Returns:
            Dict[str, Any]: 文件详情
        """
        response = await self._make_request(
            "GET", f"/v1/files/{file_id}", params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def download_file(
        self,
        project_id: str,
        file_id: str,
    ) -> httpx.Response:
        """
        从 RAG 服务下载文件并返回原始响应用于流式传输。

        与 get_file 的区别：
        - get_file: 返回 JSON 元数据
        - download_file: 返回原始文件内容（用于下载）

        Args:
            project_id: 项目 ID
            file_id: 文件 ID

        Returns:
            httpx.Response: 原始 HTTP 响应（可用于流式传输）

        Raises:
            HTTPException: 超时（504）或连接失败（502）
        """
        url = f"{self.base_url}/v1/files/{file_id}/download"
        request_id = str(uuid4())

        headers = self._get_headers()
        headers["X-Request-ID"] = request_id

        logger.info(
            f"RAG service file download: GET {url}",
            extra={
                "request_id": request_id,
                "file_id": file_id,
                "url": url,
            }
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    url=url,
                    headers=headers,
                    params={"project_id": project_id},
                )

                logger.info(
                    f"RAG service download response: {response.status_code}",
                    extra={
                        "request_id": request_id,
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "content_length": response.headers.get("content-length"),
                        "response_time": response.elapsed.total_seconds() if response.elapsed else None,
                    }
                )

                # 返回原始响应用于流式传输（不调用 _handle_response）
                return response

        except httpx.TimeoutException as e:
            logger.error(
                f"RAG service download timeout: {url}",
                extra={"request_id": request_id, "timeout": self.timeout}
            )
            raise HTTPException(
                status_code=504,
                detail="RAG service download request timed out"
            )
        except httpx.RequestError as e:
            logger.error(
                f"RAG service download request error: {e}",
                extra={"request_id": request_id, "error": str(e)}
            )
            raise HTTPException(
                status_code=502,
                detail="Failed to connect to RAG service for file download"
            )

    async def delete_file(
        self,
        project_id: str,
        file_id: str,
    ) -> None:
        """
        从 RAG 服务删除文件。

        Args:
            project_id: 项目 ID
            file_id: 文件 ID
        """
        response = await self._make_request(
            "DELETE", f"/v1/files/{file_id}", params={"project_id": project_id}
        )
        return await self._handle_response(response)

    async def upload_files_batch(
        self,
        project_id: str,
        files: List[UploadFile],
        collection_id: str,
        description: Optional[str] = None,
        language: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        批量上传多个文件到 RAG 服务。

        Args:
            project_id: 项目 ID
            files: 文件列表
            collection_id: 目标集合 ID
            description: 文件描述
            language: 文件语言
            tags: 标签

        Returns:
            Dict[str, Any]: 批量上传结果
        """
        # 准备 multipart 文件数据
        files_data = []
        for file in files:
            files_data.append(("files", (file.filename, file.file, file.content_type)))

        data = {"collection_id": collection_id, "project_id": project_id}

        if description:
            data["description"] = description
        if language:
            data["language"] = language
        if tags:
            data["tags"] = tags

        response = await self._make_request(
            "POST", "/v1/files/batch", files=files_data, data=data
        )
        return await self._handle_response(response)

    async def list_file_documents(
        self,
        project_id: str,
        file_id: str,
        content_type: Optional[str] = None,
        chunk_index: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        列出特定文件的文档块/分块。

        Args:
            project_id: 项目 ID
            file_id: 文件 ID
            content_type: 内容类型过滤
            chunk_index: 分块索引过滤
            limit: 每页数量
            offset: 分页偏移量

        Returns:
            Dict[str, Any]: 文档块列表
        """
        params: Dict[str, Any] = {
            "project_id": project_id,
            "limit": limit,
            "offset": offset,
        }
        if content_type:
            params["content_type"] = content_type
        if chunk_index is not None:
            params["chunk_index"] = chunk_index

        response = await self._make_request(
            "GET", f"/v1/files/{file_id}/documents", params=params
        )
        return await self._handle_response(response)

    # =========================================================================
    # 3. 网页爬取管理 (Website Pages Management)
    # =========================================================================

    async def list_website_pages(
        self,
        project_id: str,
        collection_id: str,
        status: Optional[str] = None,
        depth: Optional[int] = None,
        parent_page_id: Optional[str] = None,
        tree_depth: Optional[int] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        列出集合中的所有页面。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            status: 页面状态过滤
            depth: 爬取深度过滤
            parent_page_id: 父页面 ID 过滤
            tree_depth: 包含的子层级数量
                - 0 或 None: 扁平列表（无子节点）
                - 1: 仅包含直接子节点
                - 2: 包含子节点和孙节点
                - -1: 包含所有后代（无限深度）
            limit: 每页数量
            offset: 分页偏移量

        Returns:
            Dict[str, Any]: 页面列表响应
        """
        params: Dict[str, Any] = {
            "project_id": project_id,
            "collection_id": collection_id,
            "limit": limit,
            "offset": offset,
        }
        if status:
            params["status"] = status
        if depth is not None:
            params["depth"] = depth
        if parent_page_id:
            params["parent_page_id"] = parent_page_id
        if tree_depth is not None:
            params["tree_depth"] = tree_depth

        response = await self._make_request("GET", "/v1/websites/pages", params=params)
        return await self._handle_response(response)

    async def get_website_page(
        self,
        project_id: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """
        获取特定页面的详情。

        Args:
            project_id: 项目 ID
            page_id: 页面 ID

        Returns:
            Dict[str, Any]: 页面详情
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "GET", f"/v1/websites/pages/{page_id}", params=params
        )
        return await self._handle_response(response)

    async def add_website_page(
        self,
        project_id: str,
        collection_id: str,
        page_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        向集合添加要爬取的页面。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            page_data: 页面数据（URL、深度等）

        Returns:
            Dict[str, Any]: 添加的页面信息
        """
        params = {"project_id": project_id, "collection_id": collection_id}
        response = await self._make_request(
            "POST", "/v1/websites/pages", params=params, json_data=page_data
        )
        return await self._handle_response(response)

    async def delete_website_page(
        self,
        project_id: str,
        page_id: str,
    ) -> None:
        """
        从集合中删除页面。

        Args:
            project_id: 项目 ID
            page_id: 页面 ID
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "DELETE", f"/v1/websites/pages/{page_id}", params=params
        )
        await self._handle_response(response)

    async def recrawl_website_page(
        self,
        project_id: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """
        触发重新爬取已存在的页面。

        Args:
            project_id: 项目 ID
            page_id: 页面 ID

        Returns:
            Dict[str, Any]: 重新爬取结果
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "POST", f"/v1/websites/pages/{page_id}/recrawl", params=params
        )
        return await self._handle_response(response)

    async def crawl_deeper_from_page(
        self,
        project_id: str,
        page_id: str,
        crawl_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        从已存在页面提取链接并将其添加到爬取队列。

        Args:
            project_id: 项目 ID
            page_id: 页面 ID
            crawl_data: 爬取配置

        Returns:
            Dict[str, Any]: 爬取结果
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "POST", f"/v1/websites/pages/{page_id}/crawl-deeper",
            params=params,
            json_data=crawl_data
        )
        return await self._handle_response(response)

    async def get_crawl_progress(
        self,
        project_id: str,
        collection_id: str,
    ) -> Dict[str, Any]:
        """
        获取集合的爬取进度。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID

        Returns:
            Dict[str, Any]: 爬取进度信息
        """
        params = {"project_id": project_id, "collection_id": collection_id}
        response = await self._make_request(
            "GET", "/v1/websites/progress", params=params
        )
        return await self._handle_response(response)

    # =========================================================================
    # 4. QA 对管理 (QA Pairs Management)
    # =========================================================================

    async def create_qa_pair(
        self,
        project_id: str,
        collection_id: str,
        qa_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        在集合中创建单个 QA 对。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            qa_data: QA 对数据（问题、答案、分类等）

        Returns:
            Dict[str, Any]: 创建的 QA 对信息
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "POST", f"/v1/collections/{collection_id}/qa-pairs",
            params=params,
            json_data=qa_data
        )
        return await self._handle_response(response)

    async def list_qa_pairs(
        self,
        project_id: str,
        collection_id: str,
        limit: int = 20,
        offset: int = 0,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        列出集合中的 QA 对。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            limit: 每页数量
            offset: 分页偏移量
            category: 分类过滤
            status: 状态过滤

        Returns:
            Dict[str, Any]: QA 对列表响应
        """
        params: Dict[str, Any] = {
            "project_id": project_id,
            "limit": limit,
            "offset": offset,
        }
        if category:
            params["category"] = category
        if status:
            params["status"] = status

        response = await self._make_request(
            "GET", f"/v1/collections/{collection_id}/qa-pairs", params=params
        )
        return await self._handle_response(response)

    async def batch_create_qa_pairs(
        self,
        project_id: str,
        collection_id: str,
        qa_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        在集合中批量创建 QA 对。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            qa_data: 批量 QA 对数据

        Returns:
            Dict[str, Any]: 批量创建结果
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "POST", f"/v1/collections/{collection_id}/qa-pairs/batch",
            params=params,
            json_data=qa_data
        )
        return await self._handle_response(response)

    async def import_qa_pairs(
        self,
        project_id: str,
        collection_id: str,
        import_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        从 JSON/CSV 导入 QA 对。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID
            import_data: 导入数据（格式和内容）

        Returns:
            Dict[str, Any]: 导入结果
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "POST", f"/v1/collections/{collection_id}/qa-pairs/import",
            params=params,
            json_data=import_data
        )
        return await self._handle_response(response)

    async def get_qa_pair(
        self,
        project_id: str,
        qa_pair_id: str,
    ) -> Dict[str, Any]:
        """
        根据 ID 获取单个 QA 对。

        Args:
            project_id: 项目 ID
            qa_pair_id: QA 对 ID

        Returns:
            Dict[str, Any]: QA 对详情
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "GET", f"/v1/qa-pairs/{qa_pair_id}", params=params
        )
        return await self._handle_response(response)

    async def update_qa_pair(
        self,
        project_id: str,
        qa_pair_id: str,
        qa_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        更新 QA 对。

        Args:
            project_id: 项目 ID
            qa_pair_id: QA 对 ID
            qa_data: 更新数据

        Returns:
            Dict[str, Any]: 更新后的 QA 对信息
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "PUT", f"/v1/qa-pairs/{qa_pair_id}",
            params=params,
            json_data=qa_data
        )
        return await self._handle_response(response)

    async def delete_qa_pair(
        self,
        project_id: str,
        qa_pair_id: str,
    ) -> None:
        """
        删除 QA 对。

        Args:
            project_id: 项目 ID
            qa_pair_id: QA 对 ID
        """
        params = {"project_id": project_id}
        response = await self._make_request(
            "DELETE", f"/v1/qa-pairs/{qa_pair_id}", params=params
        )
        await self._handle_response(response)

    async def list_qa_categories(
        self,
        project_id: str,
        collection_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        获取项目的所有 QA 对分类。

        Args:
            project_id: 项目 ID
            collection_id: 集合 ID 过滤（可选）

        Returns:
            Dict[str, Any]: 分类列表
        """
        params: Dict[str, Any] = {"project_id": project_id}
        if collection_id:
            params["collection_id"] = collection_id

        response = await self._make_request(
            "GET", "/v1/qa-categories", params=params
        )
        return await self._handle_response(response)


# =============================================================================
# 全局 RAG 客户端实例
# =============================================================================

# 导出全局单例，供其他模块使用
rag_client = RAGServiceClient()