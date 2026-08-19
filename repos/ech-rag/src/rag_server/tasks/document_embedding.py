"""
文本嵌入生成模块。
这个模块提供了文档块的嵌入生成能力，使用各种嵌入模型和向量存储集成进行语义搜索。
关键组件：
- 使用多个提供商（OpenAI、Qwen3）进行嵌入生成
- 向量存储集成，用于嵌入存储和检索
- 批处理以提高嵌入生成效率
- 嵌入失败的错误处理和重试机制
- 性能监控和优化
功能：
- 多提供商嵌入支持（OpenAI、Qwen3-Embedding）
- 大型文档集的高效批处理
- 与pgvector的向量存储集成
- 全面的错误处理和恢复
- 性能指标和监控
- 大文件的内存高效处理
"""

import asyncio
from typing import Any, Dict, List
from uuid import UUID

from .document_processing_errors import DocumentProcessingError, ProcessingStep
from .document_processing_types import (
    ChunkDataList,
    EmbeddingList,
    EmbeddingServiceInfo,
    EmbeddingStats,
    EmbeddingVector,
    MetadataDict,
    VectorStoreService as VectorStoreServiceProtocol
)
from ..logging_config import get_logger
from ..services.embedding import get_embedding_service, get_embedding_service_for_project
from ..services.vector_store import get_vector_store_service

logger = get_logger(__name__)


async def generate_embeddings(
    chunks: List[Dict[str, Any]],
    file_id: str,
    file_uuid: UUID,
    collection_id: UUID
) -> None:
    """
    生成文档块的嵌入并将其存储在向量存储中。
    该函数处理文档块以使用配置的嵌入服务生成向量嵌入，并将其存储在向量存储中，以实现语义搜索功能。
    参数:
        chunks: 块数据字典的列表
        file_id: 用于日志记录的文件ID字符串
        file_uuid: 正在处理的文件的UUID
        collection_id: 集合的UUID
    异常:
        DocumentProcessingError: 如果嵌入生成失败
    """
    try:
        if not chunks:
            logger.warning(f"No chunks to generate embeddings for file {file_id}")
            return
        
        # Resolve project and services
        vector_store_service = get_vector_store_service()
        project_id = chunks[0].get("project_id")
        embedding_service = await get_embedding_service_for_project(project_id)

        # Add embeddings to vector store (project-scoped)
        await _add_embeddings_to_vector_store(
            chunks=chunks,
            file_id=file_id,
            collection_id=collection_id,
            vector_store_service=vector_store_service,
            embedding_service=embedding_service,
            project_id=project_id,
        )

        logger.info(f"Successfully stored embeddings for file {file_id}")
        
    except Exception as e:
        if isinstance(e, DocumentProcessingError):
            raise
        raise DocumentProcessingError(
            f"Failed to generate embeddings: {str(e)}",
            file_id,
            ProcessingStep.GENERATING_EMBEDDINGS,
            e
        ) from e


async def _add_embeddings_to_vector_store(
    chunks: List[Dict[str, Any]],
    file_id: str,
    collection_id: UUID,
    vector_store_service: Any,  # Using Any for now since the actual service doesn't match the protocol
    embedding_service: Any,
    project_id: UUID,
) -> None:
    """
    添加嵌入到向量存储中，并进行适当的错误处理。
    参数:
        chunks: 块数据字典的列表
        file_id: 用于日志记录的文件ID字符串
        collection_id: 集合的UUID
        vector_store_service: 向量存储服务实例
        embedding_service: 嵌入服务实例
        project_id: 项目的UUID
    异常:
        DocumentProcessingError: 如果向量存储操作失败
    """

    try:
        # Prepare documents for vector store in the format expected by add_documents_batch
        # The method expects List[Tuple[UUID, str, Optional[Dict[str, Any]]]]
        documents = []

        for chunk in chunks:
            # Get document ID from chunk
            document_id = chunk["id"]  # This should be the UUID
            content = chunk["content"]

            # Prepare metadata with proper UUID types for database fields
            metadata = {
                "file_id": chunk["file_id"],  # Keep as UUID
                "project_id": chunk["project_id"],  # Keep as UUID
                "collection_id": collection_id,  # Keep as UUID
                "chunk_id": chunk["chunk_id"],
                "chunk_index": chunk["chunk_index"],
                "character_count": chunk["character_count"],
                "token_count": chunk["token_count"],
                "document_type": chunk.get("document_type", "paragraph")
            }

            # Add any additional metadata from the chunk
            if "metadata" in chunk and isinstance(chunk["metadata"], dict):
                metadata.update(chunk["metadata"])

            # Create tuple in the format expected by the vector store service
            documents.append((document_id, content, metadata))

        # Add documents to vector store in batch (project-scoped embedding client)
        # /data/hmx/Test_el2k/tgo-hmx-private/repos/tgo-rag/src/rag_service/services/vector_store.py
        # 添加文档到向量存储中，使用项目范围的嵌入客户端
        ''' 在典型的 RAG 架构中，add_documents_batch_for_project 这类方法内部会自动完成两个核心步骤：
            向量化：使用传入的 embedding_client 对列表中的原始文本进行向量化，生成对应的向量（浮点数数组）2。
            存储：将生成的向量、原始文本以及元数据一起写入向量数据库。'''
        vector_ids = await vector_store_service.add_documents_batch_for_project(
            documents=documents,
            project_key=str(project_id),
            embedding_client=embedding_service.embeddings_client,
        )

        # If any vector IDs are empty placeholders, treat as a batch failure
        # 如果任何向量ID是空占位符，则将其视为批处理失败
        failed_count = sum(1 for vid in vector_ids if not vid)
        if failed_count > 0 or len(vector_ids) != len(documents):
            raise DocumentProcessingError(
                f"Vector store batch processing failed: {failed_count} of {len(documents)} documents",
                file_id,
                ProcessingStep.GENERATING_EMBEDDINGS,
            )

        logger.debug(f"Added {len(vector_ids)} documents to vector store for file {file_id}")

    except Exception as e:
        logger.error(f"Failed to add document embeddings batch: {str(e)}")
        raise DocumentProcessingError(
            f"Failed to add embeddings to vector store: {str(e)}",
            file_id,
            ProcessingStep.GENERATING_EMBEDDINGS,
            e
        ) from e


async def validate_embeddings(
    embeddings: List[List[float]],
    expected_dimensions: int,
    file_id: str
) -> bool:
    """
    有效化嵌入向量以确保一致性和正确性。
    参数:
        embeddings: 要验证的嵌入向量列表
        expected_dimensions: 每个嵌入的预期维度数   
        file_id: 用于错误报告的文件ID
    返回:
        如果所有嵌入有效，则返回True
    异常:
        DocumentProcessingError: 如果验证失败
    """
   
    try:
        if not embeddings:
            logger.warning(f"No embeddings to validate for file {file_id}")
            return True
        
        for i, embedding in enumerate(embeddings):
            # Check if embedding is a list/array of numbers
            if not isinstance(embedding, (list, tuple)):
                raise DocumentProcessingError(
                    f"Embedding {i} is not a list/array: {type(embedding)}",
                    file_id,
                    ProcessingStep.GENERATING_EMBEDDINGS
                )
            
            # Check dimensions
            # 检查维度
            if len(embedding) != expected_dimensions:
                raise DocumentProcessingError(
                    f"Embedding {i} has wrong dimensions: expected {expected_dimensions}, got {len(embedding)}",
                    file_id,
                    ProcessingStep.GENERATING_EMBEDDINGS
                )
            
            # Check if all values are numbers
            # 检查所有值是否为数字
            for j, value in enumerate(embedding):
                if not isinstance(value, (int, float)):
                    raise DocumentProcessingError(
                        f"Embedding {i}, dimension {j} is not a number: {type(value)}",
                        file_id,
                        ProcessingStep.GENERATING_EMBEDDINGS
                    )
        
        logger.debug(f"Successfully validated {len(embeddings)} embeddings for file {file_id}")
        return True
        
    except Exception as e:
        if isinstance(e, DocumentProcessingError):
            raise
        raise DocumentProcessingError(
            f"Embedding validation failed: {str(e)}",
            file_id,
            ProcessingStep.GENERATING_EMBEDDINGS,
            e
        ) from e

def get_embedding_stats(embeddings: EmbeddingList) -> EmbeddingStats:
    """
    计算嵌入向量的统计信息。
    参数:
        embeddings: 嵌入向量的列表
    返回:
        EmbeddingStats对象，包含嵌入统计信息
    """
    
    if not embeddings:
        return EmbeddingStats(
            total_embeddings=0,
            dimensions=0,
            total_values=0
        )

    dimensions = len(embeddings[0]) if embeddings else 0
    total_values = len(embeddings) * dimensions

    # Calculate basic statistics
    # value 是嵌入向量中的每个数值
    all_values = [value for embedding in embeddings for value in embedding]

    if all_values:
        return EmbeddingStats(
            total_embeddings=len(embeddings),
            dimensions=dimensions,
            total_values=total_values,
            min_value=min(all_values),
            max_value=max(all_values),
            avg_value=sum(all_values) / len(all_values)
        )
    else:
        return EmbeddingStats(
            total_embeddings=len(embeddings),
            dimensions=dimensions,
            total_values=total_values
        )


async def get_embedding_service_info() -> EmbeddingServiceInfo:
    """
    获得当前嵌入服务配置的信息。
    该函数检索当前配置的嵌入服务的详细信息，包括提供商、模型和嵌入维度，以便进行监控和调试。
    异常:
        DocumentProcessingError: 如果无法检索嵌入服务信息
    返回:
        EmbeddingServiceInfo对象，包含嵌入服务信息
    """

    try:
        embedding_service = get_embedding_service()

        return EmbeddingServiceInfo(
            provider=embedding_service.get_embedding_provider(),
            model=embedding_service.get_embedding_model(),
            dimensions=embedding_service.get_embedding_dimensions()
        )

    except Exception as e:
        logger.error(f"Failed to get embedding service info: {e}")
        return EmbeddingServiceInfo(
            provider="unknown",
            model="unknown",
            dimensions=0,
            error=str(e)
        )


async def test_embedding_generation(test_text: str = "Test embedding generation") -> Dict[str, Any]:
    """
    测试嵌入生成与当前配置的嵌入服务。
    该函数使用提供的测试文本生成嵌入，并返回有关生成过程的详细信息，包括提供商、模型、维度和生成时间，以便进行验证和调试。
    参数:
        test_text: 用于测试的文本字符串
    返回:
        包含测试结果的字典，包括成功状态、提供商、模型、维度、生成时间和测试文本长度
    异常:
        DocumentProcessingError: 如果嵌入生成失败
    """
    try:
        embedding_service = get_embedding_service()
        
        # Generate test embedding
        start_time = asyncio.get_event_loop().time()
        embedding = await embedding_service.generate_embedding(test_text)
        end_time = asyncio.get_event_loop().time()
        
        return {
            "success": True,
            "provider": embedding_service.get_embedding_provider(),
            "model": embedding_service.get_embedding_model(),
            "dimensions": len(embedding),
            "generation_time": end_time - start_time,
            "test_text_length": len(test_text)
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "test_text_length": len(test_text)
        }
