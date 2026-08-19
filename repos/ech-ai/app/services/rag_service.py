"""RAG Service client for external collection data retrieval.
# 本模块：RAG微服务HTTP异步客户端
# 业务主服务与独立RAG向量知识库服务通信，所有向量库、知识库集合、文档、Embedding配置都托管在RAG微服务，本服务只存ID，通过http调用拿数据
"""

import uuid
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.exceptions import NotFoundError, ValidationError


class CollectionData(BaseModel):
    """Collection data from RAG service.
    # RAG微服务返回的知识库集合完整元数据模型
    # 注意：业务数据库仅存储collection_id，集合名称、描述等元数据全部存在RAG服务，需要远程拉取
    """
    id: uuid.UUID = Field(description="Collection ID")                     # 知识库集合唯一UUID
    display_name: str = Field(description="Human-readable collection name")# 前端展示用集合名称
    description: Optional[str] = Field(default=None, description="Collection description") # 集合描述
    collection_metadata: Optional[Dict] = Field(default=None, description="Collection metadata") # 自定义扩展元数据
    created_at: str = Field(description="Creation timestamp")              # 创建时间戳（字符串格式）
    updated_at: str = Field(description="Last update timestamp")          # 最后更新时间戳
    deleted_at: Optional[str] = Field(default=None, description="Deletion timestamp") # 软删除时间，非空代表已删除


class CollectionBatchRequest(BaseModel):
    """Request model for batch collection retrieval.
    # 批量查询知识库集合的请求体模型（代码内实际没有实例化，只是定义报文结构做参考）
    """
    collection_ids: List[str] = Field(description="List of collection IDs to retrieve")


class CollectionBatchResponse(BaseModel):
    """Response model for batch collection retrieval.
    # 批量查询知识库集合返回报文模型
    # 设计亮点：不会部分缺失直接抛异常，区分查到的集合 + 不存在的ID，交给上层业务决定怎么处理
    """
    collections: List[CollectionData] = Field(description="Found collections") # 查询成功存在的集合列表
    not_found: List[str] = Field(description="Collection IDs that were not found") # 找不到的集合ID列表


class RAGServiceClient:
    """Client for interacting with the external RAG service.
    # RAG微服务异步HTTP客户端类，封装全部和RAG交互接口、异常处理
    """

    def __init__(self):
        """Initialize the RAG service client.
        # 初始化客户端，从配置读取RAG服务地址，设置http请求超时时间
        """
        self.base_url = settings.rag_service_url  # RAG微服务根地址，读取环境配置
        self.timeout = 30.0                       # http请求超时30秒，向量检索耗时较长，超时设置偏大

    async def get_collections_batch(
        self,
        collection_ids: List[str],
        project_id: str
    ) -> CollectionBatchResponse:
        """
        Retrieve multiple collections by their IDs from the RAG service.
        # 批量获取多个知识库集合元数据，调用RAG接口 POST /v1/collections/batch

        Args:
            collection_ids: List of collection ID strings 待查询的知识库ID字符串列表
            project_id: Project ID 项目ID，做租户隔离，RAG侧根据project_id做权限隔离

        Returns:
            CollectionBatchResponse with found collections and not found IDs

        Raises:
            ValidationError: If RAG service returns validation error RAG返回参数错误
            NotFoundError: If RAG service is unavailable RAG服务网络不通、连接失败
        """
        # 边界处理：传入空ID列表，直接返回空结果，不发起http请求
        if not collection_ids:
            return CollectionBatchResponse(collections=[], not_found=[])

        # httpx异步客户端，with上下文自动关闭http连接
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # post请求，project_id放在url query参数，集合ID放在请求body json
                response = await client.post(
                    f"{self.base_url}/v1/collections/batch",
                    params={"project_id": project_id},
                    json={"collection_ids": collection_ids},
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == 200:
                    # 请求成功，json反序列化为pydantic模型返回
                    data = response.json()
                    return CollectionBatchResponse(**data)
                elif response.status_code == 400:
                    # 请求参数非法，抛出业务层校验异常
                    raise ValidationError(
                        "Bad request to RAG service",
                        "collections",
                        {"status_code": response.status_code}
                    )
                elif response.status_code == 422:
                    # pydantic校验失败，RAG返回的参数校验错误，把detail透传给上层
                    error_data = response.json()
                    raise ValidationError(
                        f"Invalid collection IDs: {error_data.get('detail', 'Unknown validation error')}",
                        "collections",
                        {"status_code": response.status_code, "detail": error_data}
                    )
                else:
                    # 其他http状态码，抛出HTTPStatusError，进入下方except捕获
                    response.raise_for_status()

            except httpx.RequestError as e:
                # 网络异常：连接超时、DNS解析失败、服务无法访问，抛出NotFoundError
                raise NotFoundError(
                    "RAG Service",
                    f"Unable to connect to RAG service: {str(e)}"
                )
            except httpx.HTTPStatusError as e:
                # http状态码异常捕获
                if e.response.status_code == 404:
                    # 404：全部集合不存在，返回结果，not_found填充全部传入ID，不抛异常
                    return CollectionBatchResponse(
                        collections=[],
                        not_found=collection_ids
                    )
                else:
                    # 其余状态码，包装为业务校验异常
                    raise ValidationError(
                        f"RAG service error: {e.response.status_code}",
                        "collections",
                        {"status_code": e.response.status_code}
                    )

    async def validate_collections_exist(
        self,
        collection_ids: List[str],
        project_id: str
    ) -> None:
        """
        Validate that collections exist in the RAG service.
        # 校验知识库集合是否真实存在，用于创建Agent绑定知识库时校验ID合法性
        # 只要有任意一个ID不存在，直接抛出NotFoundError

        Args:
            collection_ids: List of collection ID strings to validate
            project_id: Project ID

        Raises:
            NotFoundError: If any collection is not found
            ValidationError: If validation fails
        """
        # 空列表无需校验直接返回
        if not collection_ids:
            return

        # 调用批量查询接口
        batch_response = await self.get_collections_batch(collection_ids, project_id)

        # 如果not_found不为空，抛出异常告知哪些ID找不到
        if batch_response.not_found:
            raise NotFoundError(
                "Collection",
                f"Collections not found: {', '.join(batch_response.not_found)}"
            )

    async def get_collection(
        self,
        collection_id: str,
        project_id: str
    ) -> Optional[CollectionData]:
        """
        Retrieve a single collection by ID from the RAG service.
        # 获取单个知识库集合信息，复用批量接口（简化代码，不用单独写单条接口）

        Args:
            collection_id: Collection ID string
            project_id: Project ID

        Returns:
            CollectionData if found, None otherwise 存在返回实体，不存在返回None

        Raises:
            ValidationError: If RAG service returns validation error
        """
        # 把单个ID包装成列表调用批量接口
        batch_response = await self.get_collections_batch([collection_id], project_id)

        if batch_response.collections:
            return batch_response.collections[0]
        return None

    async def search_documents(
        self,
        collection_id: str,
        project_id: str,
        query: str,
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Search documents in a collection.
        # RAG向量检索接口：在指定知识库内执行向量相似度搜索，返回检索文档片段
        # 返回原始字典，不做pydantic模型解析（文档检索返回结构复杂，上层自己解析）

        Args:
            collection_id: Collection ID string 知识库集合ID
            project_id: Project ID string or UUID 项目租户ID
            query: Search query 用户查询文本
            limit: Maximum number of results 返回topN结果数量，默认10

        Returns:
            Search results dictionary RAG检索原始json字典
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/collections/{collection_id}/documents/search",
                    params={"project_id": str(project_id)},
                    json={"query": query, "limit": limit},
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                # http状态异常，包装校验错误，把RAG返回原始文本放异常detail方便排查
                raise ValidationError(
                    f"RAG search error: {e.response.status_code}",
                    "collections",
                    {"status_code": e.response.status_code, "detail": e.response.text}
                )
            except httpx.RequestError as e:
                # 网络不通，抛出服务找不到异常
                raise NotFoundError(
                    "RAG Service",
                    f"Unable to connect to RAG service for search: {str(e)}"
                )

    async def batch_sync_embedding_configs(
        self,
        configs: List["EmbeddingConfigCreate"],
    ) -> "EmbeddingConfigBatchSyncResponse":
        """Batch upsert embedding configurations in the RAG service.
        # 批量同步Embedding向量模型配置到RAG微服务，新增/更新（upsert）
        # 对应RAG接口 POST /v1/embedding-configs/batch-sync

        :param configs: 需要同步的向量模型配置列表
        """
        # 没有配置需要同步直接返回空结果
        if not configs:
            return EmbeddingConfigBatchSyncResponse(
                success_count=0, failed_count=0, errors=[]
            )

        # pydantic模型转json字典，exclude_none=True 过滤掉值为None字段，不传给RAG服务
        payload = {"configs": [c.model_dump(mode="json", exclude_none=True) for c in configs]}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/embedding-configs/batch-sync",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if response.status_code == 200:
                    data = response.json()
                    return EmbeddingConfigBatchSyncResponse(**data)
                elif response.status_code == 422:
                    # 请求体参数校验失败，透传RAG返回的错误详情
                    data = response.json()
                    raise ValidationError(
                        "Invalid embedding config payload",
                        "embedding-configs",
                        {"detail": data},
                    )
                else:
                    response.raise_for_status()

            except httpx.RequestError as e:
                # 网络连接失败
                raise NotFoundError(
                    "RAG Service",
                    f"Unable to connect to RAG service for embedding sync: {str(e)}",
                )
            except httpx.HTTPStatusError as e:
                # http状态异常，包装业务异常
                raise ValidationError(
                    f"RAG service error during embedding sync: {e.response.status_code}",
                    "embedding-configs",
                    {"status_code": e.response.status_code},
                )


# 全局单例客户端实例，项目各处直接导入 rag_service_client 使用，不需要重复new对象
rag_service_client = RAGServiceClient()


class EmbeddingConfigCreate(BaseModel):
    """Embedding configuration item to sync to RAG service.
    # 需要同步给RAG的向量模型配置模型
    """
    project_id: uuid.UUID          # 所属项目ID，租户隔离
    provider: str                  # Embedding服务商，如 openai/qwen等
    model: str                     # 向量模型名称
    # Optional extras supported by RAG; we pass when available
    dimensions: Optional[int] = Field(default=None) # 向量输出维度
    batch_size: Optional[int] = Field(default=None) # 向量化批量大小
    api_key: Optional[str] = None                    # 服务商API密钥
    base_url: Optional[str] = None                   # 自定义服务商接口地址
    is_active: Optional[bool] = True                # 是否启用该向量配置


class EmbeddingConfigBatchSyncRequest(BaseModel):
    """批量同步向量配置请求模型，代码内仅做结构参考，没有实际实例化"""
    configs: List[EmbeddingConfigCreate]


class EmbeddingConfigBatchSyncResponse(BaseModel):
    """批量同步向量配置返回结果"""
    success_count: int                # 同步成功数量
    failed_count: int                 # 同步失败数量
    errors: Optional[List[Dict]] = None # 失败项错误详情列表