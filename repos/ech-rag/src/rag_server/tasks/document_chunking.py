"""
这是一段关于文本处理模块的技术文档，用自然流畅的中文可以这样翻译：
文档分块与文本分割模块
本模块提供文本分块功能，旨在实现最佳的检索增强生成（RAG）性能。它支持通过可配置的参数和策略来处理文档分割，从而生成具有完整语义的文本块，以便于后续的向量嵌入（Embedding）生成。
核心组件：
    基于 RecursiveCharacterTextSplitter（递归字符文本分割器）的可配置文本拆分
    针对嵌入模型优化的文本块大小
    重叠（Overlap）管理机制，用于保留上下文连贯性
    Token 计数与估算工具
    文本块元数据的管理与追踪
主要特性：
    采用基于递归字符的分割方式，以保留自然的文本边界
    支持自定义文本块大小和重叠参数
    提供 Token 计数功能，确保文本块大小精准
    在分割过程中完整保留元数据
    针对大型文档进行了性能优化
"""

import re
from typing import Any, Dict, List
from uuid import UUID, uuid4

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .document_processing_errors import DocumentProcessingError, ProcessingStep
from .document_processing_types import (
    ChunkingStats,
    DocumentList,
    MetadataDict,
    TextSplitter as TextSplitterProtocol
)
from ..config import get_settings
from ..logging_config import get_logger

logger = get_logger(__name__)
# chunk_documents 指定了一个函数，用于将文档分割成适合嵌入生成和检索的较小块。
def chunk_documents(
    documents: DocumentList,
    file_id: str,
    file_uuid: UUID,
    collection_id: UUID,
    project_id: UUID
) -> List[Dict[str, Any]]:
    """
    分割文档为适合 RAG 性能的块。
    这个函数接收已加载的文档，并将其分割成较小的块，这些块的大小经过优化，以便于嵌入生成和检索。
    参数:
        documents: 要分割的 Document 对象列表
        file_id: 用于日志记录的文件字符串 ID
        file_uuid: 正在处理的文件的 UUID
        collection_id: 文件所属集合的 UUID
    返回值:
        包含准备存储到数据库的块数据的字典列表
    抛出:
        DocumentProcessingError: 如果分块失败，则抛出此异常
    """
    
    try:
        if not documents:
            logger.warning(f"No documents to chunk for file {file_id}")
            return []
        
        settings = get_settings()
        
        # Create text splitter with optimized parameters
        text_splitter = _create_text_splitter(settings)
        
        # Split documents into chunks
        chunks = []
        total_chunks = 0
        # 遍历每个文档并将其分割成块
        for doc_index, document in enumerate(documents):
            try:
                # Split the document into chunks
                doc_chunks = text_splitter.split_documents([document])
                
                # Process each chunk
                for chunk_index, chunk in enumerate(doc_chunks):
                    chunk_data = _create_chunk_data(
                        chunk=chunk,
                        file_uuid=file_uuid,
                        collection_id=collection_id,
                        project_id=project_id,
                        file_id=file_id,
                        doc_index=doc_index,
                        chunk_index=chunk_index + total_chunks
                    )
                    chunks.append(chunk_data)
                
                total_chunks += len(doc_chunks)
                logger.debug(f"Created {len(doc_chunks)} chunks from document {doc_index} in file {file_id}")
                
            except Exception as e:
                logger.error(f"Failed to chunk document {doc_index} in file {file_id}: {e}")
                raise DocumentProcessingError(
                    f"Failed to chunk document {doc_index}: {str(e)}",
                    file_id,
                    ProcessingStep.CHUNKING_DOCUMENTS,
                    e
                ) from e
        
        logger.info(f"Successfully created {len(chunks)} chunks from {len(documents)} documents for file {file_id}")
        return chunks
        
    except Exception as e:
        if isinstance(e, DocumentProcessingError):
            raise
        raise DocumentProcessingError(
            f"Document chunking failed: {str(e)}",
            file_id,
            ProcessingStep.CHUNKING_DOCUMENTS,
            e
        ) from e

def _create_text_splitter(settings: Any) -> RecursiveCharacterTextSplitter:
    """
    Create a text splitter with optimized parameters.
    
    Args:
        settings: Application settings containing chunking configuration
        
    Returns:
        Configured RecursiveCharacterTextSplitter instance
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        length_function=len,
        separators=[
            "\n\n",  # Paragraph breaks
            "\n",    # Line breaks
            " ",     # Word breaks
            ".",     # Sentence breaks
            ",",     # Clause breaks
            ""       # Character breaks (fallback)
        ],
        keep_separator=True,
        add_start_index=True
    )


def _create_chunk_data(
    chunk: Document,
    file_uuid: UUID,
    collection_id: UUID,
    project_id: UUID,
    file_id: str,
    doc_index: int,
    chunk_index: int
) -> Dict[str, Any]:
    """
    创建用于数据库存储的块数据字典。
    参数:
        chunk: 要处理的文档块
        file_uuid: 源文件的 UUID
        collection_id: 集合的 UUID
        project_id: 项目的 UUID
        file_id: 用于块命名的文件字符串 ID
        doc_index: 源文档的索引
        chunk_index: 此块的索引
    返回值:
        包含准备存储到数据库的块数据的字典
    """
    # Generate unique chunk ID
    chunk_id = f"{file_id}_chunk_{chunk_index}"
    
    # Calculate token count
    token_count = estimate_token_count(chunk.page_content)
    
    # Prepare metadata
    metadata = chunk.metadata.copy() if chunk.metadata else {}
    metadata.update({
        "chunk_index": chunk_index,
        "document_index": doc_index,
        "chunk_id": chunk_id
    })
    
    return {
        "id": uuid4(),
        "file_id": file_uuid,
        "collection_id": collection_id,
        "project_id": project_id,
        "chunk_id": chunk_id,
        "content": chunk.page_content,
        "character_count": len(chunk.page_content),
        "token_count": token_count,
        "chunk_index": chunk_index,
        "document_type": "paragraph",  # Default document type
        "metadata": metadata
    }


def estimate_token_count(text: str) -> int:
    """
    Estimate token count for a given text.
    
    This provides a rough estimation of tokens based on word count and
    character patterns. For more accurate token counting, consider using
    the actual tokenizer from your embedding model.
    
    Args:
        text: Text to estimate tokens for
        
    Returns:
        Estimated number of tokens
    """
    if not text:
        return 0
    
    # Simple estimation: roughly 4 characters per token for English text
    # This is a conservative estimate that works reasonably well for most content
    
    # Count words (more accurate for token estimation)
    words = len(text.split())
    
    # Count special characters and punctuation (often separate tokens)
    special_chars = len(re.findall(r'[^\w\s]', text))
    
    # Estimate tokens: words + some fraction of special characters
    # 得到一个粗略的估计，假设每两个特殊字符大约等于一个 token
    estimated_tokens = words + (special_chars // 2)
    
    # Ensure minimum of 1 token for non-empty text
    return max(1, estimated_tokens)

# 获得块统计信息的函数
def get_chunking_stats(chunks: List[Dict[str, Any]]) -> ChunkingStats:
    """
    Calculate statistics for a list of chunks.

    Args:
        chunks: List of chunk data dictionaries

    Returns:
        ChunkingStats object containing chunking statistics
    """
    if not chunks:
        return ChunkingStats(
            total_chunks=0,
            total_characters=0,
            total_tokens=0,
            avg_chunk_size=0,
            avg_tokens_per_chunk=0,
            min_chunk_size=0,
            max_chunk_size=0
        )

    total_characters = sum(chunk["character_count"] for chunk in chunks)
    total_tokens = sum(chunk["token_count"] for chunk in chunks)

    return ChunkingStats(
        total_chunks=len(chunks),
        total_characters=total_characters,
        total_tokens=total_tokens,
        avg_chunk_size=total_characters // len(chunks),
        avg_tokens_per_chunk=total_tokens // len(chunks),
        min_chunk_size=min(chunk["character_count"] for chunk in chunks),
        max_chunk_size=max(chunk["character_count"] for chunk in chunks)
    )

# 有效化块的函数
def validate_chunks(chunks: List[Dict[str, Any]], file_id: str) -> bool:
    """
    Validate chunk data before processing.
    
    Args:
        chunks: List of chunk data dictionaries to validate
        file_id: File ID for error reporting
        
    Returns:
        True if all chunks are valid
        
    Raises:
        DocumentProcessingError: If validation fails
    """
    try:
        if not chunks:
            logger.warning(f"No chunks to validate for file {file_id}")
            return True
        
        required_fields = ["id", "file_id", "collection_id", "chunk_id", "content", "token_count"]
        
        for i, chunk in enumerate(chunks):
            # Check required fields
            for field in required_fields:
                if field not in chunk:
                    raise DocumentProcessingError(
                        f"Chunk {i} missing required field: {field}",
                        file_id,
                        ProcessingStep.CHUNKING_DOCUMENTS
                    )
            
            # Validate content
            if not chunk["content"] or not chunk["content"].strip():
                raise DocumentProcessingError(
                    f"Chunk {i} has empty content",
                    file_id,
                    ProcessingStep.CHUNKING_DOCUMENTS
                )
            
            # Validate token count
            if chunk["token_count"] <= 0:
                raise DocumentProcessingError(
                    f"Chunk {i} has invalid token count: {chunk['token_count']}",
                    file_id,
                    ProcessingStep.CHUNKING_DOCUMENTS
                )
        
        logger.debug(f"Successfully validated {len(chunks)} chunks for file {file_id}")
        return True
        
    except Exception as e:
        if isinstance(e, DocumentProcessingError):
            raise
        raise DocumentProcessingError(
            f"Chunk validation failed: {str(e)}",
            file_id,
            ProcessingStep.CHUNKING_DOCUMENTS,
            e
        ) from e
