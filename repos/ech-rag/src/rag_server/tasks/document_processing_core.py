
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from .document_loaders import get_document_loader
from .document_chunking import chunk_documents, get_chunking_stats, validate_chunks
from .document_embedding import generate_embeddings, get_embedding_service_info
from .document_processing_errors import (
    DocumentProcessingError,
    ProcessingStep,
    ProcessingStatus,
    _handle_processing_error,
    log_processing_step,
    log_processing_success
)
from .document_processing_types import (
    DocumentList,
    FileInfo,
    ProcessingResult
)
from ..database import get_db_session
from ..models import File, FileDocument, WebsitePage

logger = logging.getLogger(__name__)

async def _update_website_page_status(
    file_uuid: UUID,
    status: str,
    error_message: Optional[str] = None
) -> None:
    """
    更新 WebsitePage 状态，如果文件是从网站爬取创建的。
    这个函数检查文件的 storage_metadata 中是否有关联的 page_id，并更新相应的 WebsitePage 状态。
    参数:
        file_uuid: 文件的 UUID
        status: WebsitePage 的新状态（'processed' 或 'failed'）
        error_message: 如果状态为 'failed'，则提供可选的错误信息
    """
    try:
        async with get_db_session() as db:
            # Load file to get storage_metadata
            result = await db.execute(
                select(File).where(File.id == file_uuid)
            )
            file_record = result.scalar_one_or_none()

            if not file_record:
                return

            # Check if this file came from website crawling
            storage_metadata = file_record.storage_metadata or {}
            page_id_str = storage_metadata.get("page_id")

            if not page_id_str:
                return  # Not a website crawl file

            try:
                page_uuid = UUID(page_id_str)
            except (ValueError, TypeError):
                logger.warning(f"Invalid page_id in storage_metadata: {page_id_str}")
                return

            # Update WebsitePage status
            page_result = await db.execute(
                select(WebsitePage).where(WebsitePage.id == page_uuid)
            )
            page = page_result.scalar_one_or_none()

            if page:
                page.status = status
                if error_message:
                    page.error_message = error_message
                await db.commit()
                logger.info(f"Updated WebsitePage {page_uuid} status to '{status}'")

    except SQLAlchemyError as e:
        logger.error(f"Failed to update WebsitePage status for file {file_uuid}: {e}")

async def update_website_page_status_by_file_id(
    file_id: str,
    status: str,
    error_message: Optional[str] = None
) -> None:
    """
    更新 WebsitePage 状态，使用 file_id 字符串。
    这是 _update_website_page_status 的一个便利包装器，处理 UUID 转换，并且在 file_id 可能无效时也可以安全调用。
    参数:
        file_id: 文件的字符串 UUID
        status: WebsitePage 的新状态（'processed' 或 'failed'）
        error_message: 如果状态为 'failed'，则提供可选的错误信息
    """
    try:
        file_uuid = UUID(file_id)
        await _update_website_page_status(file_uuid, status, error_message)
    except (ValueError, TypeError) as e:
        logger.warning(f"Invalid file_id for page status update: {file_id} - {e}")

async def process_file_async(
    file_uuid: UUID,
    collection_id: UUID,
    task_id: Optional[str] = None,
    is_qa_mode: bool = False
) -> ProcessingResult:
    """
    主要的异步文档处理函数。
    该函数协调完整的文档处理管道：
    1. 加载并验证文件信息
    2. 使用适当的文档加载器提取内容
    3. 将文档分块以实现最佳嵌入大小
    4. 使用配置的嵌入服务生成嵌入
    5. 将文档和嵌入存储到数据库中
    6. 更新文件状态和处理指标
    参数:
        file_uuid: 要处理的文件的 UUID
        collection_id: 文件所属集合的 UUID
        task_id: 可选的 Celery 任务 ID，用于进度跟踪
        is_qa_mode: 是否为文档生成 QA 对
    返回:
        包含处理结果和指标的 ProcessingResult 对象
    异常:
        DocumentProcessingError: 对于任何处理失败
    """
    start_time = time.time()
    file_id = str(file_uuid)
    
    try:
        # Update status to processing
        await _update_file_status(file_uuid, ProcessingStatus.PROCESSING)
        log_processing_step(file_id, ProcessingStep.LOADING_FILE, f"Starting document processing (QA Mode: {is_qa_mode})")
        
        # Load file information
        # 加载文件信息
        file_info = await _load_file_info(file_uuid, file_id)
        
        # Load and extract document content
        # 加载并提取文档内容
        documents = await _load_document_content(file_info, file_id)
        
        # Update status to chunking
        # 更新状态为分块
        await _update_file_status(file_uuid, ProcessingStatus.CHUNKING_DOCUMENTS)
        
        # Chunk documents
        # 文档分块以实现最佳嵌入大小
        chunks = await _chunk_documents(documents, file_id, file_uuid, collection_id, file_info.project_id)
        
        # If QA mode is enabled, generate QA pairs and append to chunks
        if is_qa_mode:
            # QA generation proceeds without explicit status update (defaults to previous state)
            # 生成 QA 对并附加到 chunks
            qa_chunks = await _generate_qa_pairs(chunks, file_id, file_uuid, collection_id, file_info.project_id)
            if qa_chunks:
                chunks.extend(qa_chunks)
        
        # Store document chunks in database
        # 将文档块存储到数据库中
        await _store_document_chunks(chunks, file_id, file_info.project_id)
        
        # Update status to generating embeddings
        # 更新状态为生成嵌入
        await _update_file_status(file_uuid, ProcessingStatus.GENERATING_EMBEDDINGS)
        
        # Generate embeddings
        # 生成嵌入
        await _generate_document_embeddings(chunks, file_id, file_uuid, collection_id)
        
        # Calculate final metrics
        processing_time = time.time() - start_time
        document_count = len(chunks)
        total_tokens = sum(chunk["token_count"] for chunk in chunks)
        
        # Update final status and metrics
        # 更新最终状态和指标
        await _update_file_completion(file_uuid, document_count, total_tokens)

        # Update associated WebsitePage status if this file came from crawling
        # 如果此文件来自爬取，则更新关联的 WebsitePage 状态
        await _update_website_page_status(file_uuid, "processed")

        # Log success
        log_processing_success(file_id, processing_time, document_count, total_tokens)

        return ProcessingResult(
            status=ProcessingStatus.COMPLETED.value,
            file_id=file_id,
            document_count=document_count,
            total_tokens=total_tokens,
            processing_time=processing_time,
            error=None
        )

    except Exception as e:
        logger.error(f"Async processing failed: {e}")
        return ProcessingResult(
            status=ProcessingStatus.FAILED.value,
            file_id=file_id,
            document_count=0,
            total_tokens=0,
            processing_time=0,
            error=str(e)
        )


async def _generate_qa_pairs(
    chunks: List[Dict[str, Any]], 
    file_id: str, 
    file_uuid: UUID, 
    collection_id: UUID, 
    project_id: UUID
) -> List[Dict[str, Any]]:
    """Generate QA pairs from document chunks."""
    from ..services.llm import get_llm_service_for_project
    from uuid import uuid4

    qa_chunks = []
    llm_service = await get_llm_service_for_project(project_id)
    
    total_chunks = len(chunks)
    logger.info(f"Starting QA generation for file {file_id} with {total_chunks} chunks")
    
    qa_inputs = []
    import asyncio
    
    for i, chunk in enumerate(chunks):
        qa_inputs.append((i, chunk))

    # Process in batches to avoid overwhelming the LLM API (configurable)
    from ..config import get_settings
    settings = get_settings()
    batch_size = settings.qa_generation_batch_size
    for k in range(0, len(qa_inputs), batch_size):
        batch = qa_inputs[k:k+batch_size]
        tasks = []
        for _, chunk in batch:
            tasks.append(llm_service.generate_qa_pairs(chunk["content"]))
        
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for idx, (original_idx, chunk) in enumerate(batch):
            result = batch_results[idx]
            
            if isinstance(result, Exception):
                logger.error(f"Error generating QA for chunk {chunk['chunk_index']}: {result}")
                continue
                
            qa_pairs = result
            if not qa_pairs:
                continue
                
            # Convert each QA pair to a document chunk
            for j, qa in enumerate(qa_pairs):
                question = qa.get("question", "").strip()
                answer = qa.get("answer", "").strip()
                
                if not question or not answer:
                    continue
                    
                # Format content as Q&A
                content = f"Question: {question}\nAnswer: {answer}"
                
                # Create QA chunk
                qa_chunk_id = f"{file_id}_qa_{chunk['chunk_index']}_{j}"
                
                qa_metadata = chunk["metadata"].copy()
                qa_metadata.update({
                    "is_qa": True,
                    "original_question": question,
                    "original_answer": answer,
                    "source_chunk_id": chunk["chunk_id"]
                })
                
                qa_chunk = {
                    "id": uuid4(),
                    "file_id": file_uuid,
                    "collection_id": collection_id,
                    "project_id": project_id,
                    "chunk_id": qa_chunk_id,
                    "content": content,
                    "character_count": len(content),
                    # Estimate tokens for QA pair
                    "token_count": len(content.split()) + 10, 
                    "chunk_index": chunk["chunk_index"], # Keep same index to appear near original? Or maybe separate.
                    "document_type": "qa_pair",
                    "metadata": qa_metadata
                }
                qa_chunks.append(qa_chunk)
                
            # Log progress every 10 chunks
            if (original_idx + 1) % 10 == 0:
                logger.info(f"QA Generation progress: {original_idx + 1}/{total_chunks} chunks processed")
            
    logger.info(f"QA Generation completed. Generated {len(qa_chunks)} QA pairs from {total_chunks} chunks.")
    return qa_chunks

# 加载文件信息的辅助函数，确保文件存在并从数据库中检索其元数据。
async def _load_file_info(file_uuid: UUID, file_id: str) -> Any:
    """Load file information from database."""
    try:
        async with get_db_session() as db:
            result = await db.execute(
                select(File).where(File.id == file_uuid)
            )
            file_info = result.scalar_one_or_none()
            
            if not file_info:
                raise DocumentProcessingError(
                    f"File not found: {file_uuid}",
                    file_id,
                    ProcessingStep.LOADING_FILE
                )
            
            log_processing_step(file_id, ProcessingStep.LOADING_FILE, f"File loaded successfully: {file_info.original_filename}")
            return file_info
            
    except Exception as e:
        if isinstance(e, DocumentProcessingError):
            raise
        raise DocumentProcessingError(
            f"Error loading file info: {str(e)}",
            file_id,
            ProcessingStep.LOADING_FILE,
            e
        ) from e

# _load_document_content 指加载文档内容，使用适当的加载器，并在必要时提供 PDF OCR 回退机制。
async def _load_document_content(file_info: Any, file_id: str) -> List[Any]:
    """Load document content using appropriate loader with PDF OCR fallback."""
    try:
        file_path = file_info.storage_path
        content_type = file_info.content_type

        # Primary: parser-based loader (fast path)
        loader = get_document_loader(file_path, content_type, file_id)
        loop = asyncio.get_event_loop()
        documents = await loop.run_in_executor(None, loader.load)

        def _is_effective(docs: List[Any]) -> bool:
            try:
                return bool(docs) and any(getattr(d, "page_content", "").strip() for d in docs)
            except Exception:
                return bool(docs)

        if _is_effective(documents):
            log_processing_step(
                file_id,
                ProcessingStep.EXTRACTING_CONTENT,
                f"Extracted content from {len(documents)} documents (primary parser)"
            )
            return documents

        # Fallback check for PDFs with no extractable text
        if content_type == "application/pdf" and not _is_effective(documents):
            raise DocumentProcessingError(
                "PDF appears to be scanned/image-based. Text extraction not supported for this PDF type. "
                "Please use a text-based PDF or enable OCR service.",
                file_id,
                ProcessingStep.EXTRACTING_CONTENT,
            )

        # If still no content, raise explicit error
        raise DocumentProcessingError(
            "No content extracted from file",
            file_id,
            ProcessingStep.EXTRACTING_CONTENT,
        )

    except Exception as e:
        if isinstance(e, DocumentProcessingError):
            raise
        raise DocumentProcessingError(
            f"Error loading document content: {str(e)}",
            file_id,
            ProcessingStep.EXTRACTING_CONTENT,
            e
        ) from e

# 函数是文档分块的核心逻辑，确保文档被分割成适合嵌入的块，并在必要时进行验证和统计记录。
async def _chunk_documents(documents: List[Any], file_id: str, file_uuid: UUID, collection_id: UUID, project_id: UUID) -> List[Dict[str, Any]]:
    """Chunk documents into optimal sizes."""
    try:
        # Chunk documents
        chunks = chunk_documents(documents, file_id, file_uuid, collection_id, project_id)
        
        # Validate chunks
        validate_chunks(chunks, file_id)
        
        # Log chunking statistics
        stats = get_chunking_stats(chunks)
        log_processing_step(
            file_id,
            ProcessingStep.CHUNKING_DOCUMENTS,
            f"Created {stats.total_chunks} chunks with {stats.total_tokens} total tokens"
        )
        
        return chunks
        
    except Exception as e:
        if isinstance(e, DocumentProcessingError):
            raise
        raise DocumentProcessingError(
            f"Error chunking documents: {str(e)}",
            file_id,
            ProcessingStep.CHUNKING_DOCUMENTS,
            e
        ) from e

# 存储文档块到数据库的函数，确保每个块都被正确映射到数据库模型，并处理任何潜在的数据库错误。
async def _store_document_chunks(chunks: List[Dict[str, Any]], file_id: str, project_id: UUID) -> None:
    """Store document chunks in database."""
    try:
        async with get_db_session() as db:
            # Create FileDocument instances
            file_documents = []
            for chunk in chunks:
                file_doc = FileDocument(
                    id=chunk["id"],
                    project_id=project_id,  # Required field
                    file_id=chunk["file_id"],
                    collection_id=chunk["collection_id"],
                    content=chunk["content"],
                    content_length=chunk["character_count"],  # character_count maps to content_length
                    token_count=chunk["token_count"],
                    chunk_index=chunk["chunk_index"],
                    content_type=chunk.get("document_type", "paragraph"),  # document_type maps to content_type
                    tags=chunk.get("metadata", {})  # metadata maps to tags
                )
                file_documents.append(file_doc)
            
            # Add all documents to session
            db.add_all(file_documents)
            await db.commit()
            
            log_processing_step(
                file_id,
                ProcessingStep.STORING_DOCUMENTS,
                f"Stored {len(file_documents)} document chunks"
            )
            
    except Exception as e:
        raise DocumentProcessingError(
            f"Error storing document chunks: {str(e)}",
            file_id,
            ProcessingStep.STORING_DOCUMENTS,
            e
        ) from e

# 生成文档块的嵌入向量的函数，确保每个块都被正确处理，并在必要时记录进度和错误。
async def _generate_document_embeddings(chunks: List[Dict[str, Any]], file_id: str, file_uuid: UUID, collection_id: UUID) -> None:
    """Generate embeddings for document chunks."""
    try:
        await generate_embeddings(chunks, file_id, file_uuid, collection_id)
        
        log_processing_step(
            file_id,
            ProcessingStep.GENERATING_EMBEDDINGS,
            f"Generated embeddings for {len(chunks)} chunks"
        )
        
    except Exception as e:
        if isinstance(e, DocumentProcessingError):
            raise
        raise DocumentProcessingError(
            f"Error generating embeddings: {str(e)}",
            file_id,
            ProcessingStep.GENERATING_EMBEDDINGS,
            e
        ) from e

# 更新文件处理状态的辅助函数，确保数据库中的状态字段被正确更新，并处理任何潜在的数据库错误。
async def _update_file_status(file_uuid: UUID, status: ProcessingStatus) -> None:
    """Update file processing status."""
    try:
        async with get_db_session() as db:
            await db.execute(
                update(File)
                .where(File.id == file_uuid)
                .values(status=status.value)
            )
            await db.commit()
            
    except SQLAlchemyError as e:
        logger.error(f"Failed to update file status to {status.value}: {e}")

# 更新文件完成状态和处理指标的函数，确保数据库中的相关字段被正确更新，并在必要时记录错误。
async def _update_file_completion(file_uuid: UUID, document_count: int, total_tokens: int) -> None:
    """Update file with completion metrics."""
    try:
        async with get_db_session() as db:
            await db.execute(
                update(File)
                .where(File.id == file_uuid)
                .values(
                    status=ProcessingStatus.COMPLETED.value,
                    document_count=document_count,
                    total_tokens=total_tokens
                )
            )
            await db.commit()
            
    except SQLAlchemyError as e:
        logger.error(f"Failed to update file completion metrics: {e}")
