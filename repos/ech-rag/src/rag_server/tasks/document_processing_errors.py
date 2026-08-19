"""
文档处理错误处理模块。
该模块为文档处理任务提供错误处理工具，包括:
    用于不同处理阶段的自定义异常类
    错误处理工具和恢复机制
    用于错误上下文的处理步骤枚举
    结构化错误报告和日志记录
关键组件:
处理步骤:错误上下文的处理阶段枚举
文档处理错误:带有详细错误信息的自定义异常
用于优雅失败恢复的错误处理工具
"""

from enum import Enum
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..database import get_db_session
from ..logging_config import get_logger
from ..models import File

logger = get_logger(__name__)
# ProcessingStep 主要用于跟踪文档处理的不同阶段，以便在发生错误时提供上下文信息。
class ProcessingStep(Enum):
    """Enumeration of document processing steps for error tracking."""
    LOADING_FILE = "loading_file"
    EXTRACTING_CONTENT = "extracting_content"
    CHUNKING_DOCUMENTS = "chunking_documents"
    GENERATING_EMBEDDINGS = "generating_embeddings"
    STORING_DOCUMENTS = "storing_documents"
    UPDATING_STATUS = "updating_status"

# ProcessingStatus 枚举用于表示文档处理的不同状态，便于在任务执行过程中进行状态跟踪和管理。
class ProcessingStatus(Enum):
    """Document processing status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    CHUNKING_DOCUMENTS = "chunking_documents"
    GENERATING_EMBEDDINGS = "generating_embeddings"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"

# DocumentProcessingError 类是一个自定义异常类，用于在文档处理过程中捕获和报告错误。它提供了详细的错误信息，
# 包括文件ID、处理步骤和原始异常，以便进行调试和日志记录。
class DocumentProcessingError(Exception):
    """
    Custom exception for document processing errors.
    
    Provides detailed error information including:
    - File ID for error tracking
    - Processing step where error occurred
    - Original exception for debugging
    - Structured error context
    """
    
    def __init__(
        self,
        message: str,
        file_id: str,
        step: ProcessingStep,
        original_exception: Optional[Exception] = None
    ):
        """
        Initialize document processing error.
        
        Args:
            message: Human-readable error message
            file_id: ID of the file being processed
            step: Processing step where error occurred
            original_exception: Original exception that caused this error
        """
        super().__init__(message)
        self.message = message
        self.file_id = file_id
        self.step = step
        self.original_exception = original_exception
    
    def __str__(self) -> str:
        """Return formatted error message."""
        return f"DocumentProcessingError in {self.step.value} for file {self.file_id}: {self.message}"
    
    def to_dict(self) -> dict:
        """Convert error to dictionary for structured logging."""
        return {
            "error_type": "DocumentProcessingError",
            "message": self.message,
            "file_id": self.file_id,
            "step": self.step.value,
            "original_exception": str(self.original_exception) if self.original_exception else None
        }    

# _handle_processing_error 函数是一个异步函数，用于处理文档处理过程中发生的错误。它会记录错误信息，并尝试更新数据库中对应文件的状态为失败。
async def _handle_processing_error(
    file_uuid: UUID,
    file_id: str,
    processing_error: Exception,
    step: ProcessingStep
) -> None:
    """
    Handle processing errors by updating file status and logging.
    
    Args:
        file_uuid: UUID of the file being processed
        file_id: String ID of the file for logging
        processing_error: Exception that occurred during processing
        step: Processing step where error occurred
    """
    try:
        # Log the error with context
        error_context = {
            "file_id": file_id,
            "file_uuid": str(file_uuid),
            "step": step.value,
            "error_type": type(processing_error).__name__,
            "error_message": str(processing_error)
        }
        
        logger.error(f"Document processing failed for file {file_id}: {processing_error}", extra=error_context)
        
        # Update file status to failed
        async with get_db_session() as db:
            try:
                # Get the file record
                result = await db.execute(
                    select(File).where(File.id == file_uuid)
                )
                file_record = result.scalar_one_or_none()
                
                if file_record:
                    file_record.status = ProcessingStatus.FAILED.value
                    file_record.error_message = str(processing_error)
                    await db.commit()
                    logger.info(f"Updated file status to failed for file {file_id}")
                else:
                    logger.warning(f"File record not found for UUID {file_uuid}")
                    
            except SQLAlchemyError as db_error:
                await db.rollback()
                logger.error(f"Failed to update file status for {file_id}: {db_error}")
                
    except Exception as e:
        # Log the error handling failure, but don't raise to avoid masking original error
        logger.error(f"Error handling failed for file {file_id}: {e}")

# 创建一个 DocumentProcessingError 实例的工厂函数，提供了统一的方式来创建带有上下文信息的错误对象。
def create_processing_error(
    message: str,
    file_id: str,
    step: ProcessingStep,
    original_exception: Optional[Exception] = None
) -> DocumentProcessingError:
    """
    Create a DocumentProcessingError with proper context.
    
    Args:
        message: Error message
        file_id: File ID for context
        step: Processing step where error occurred
        original_exception: Original exception if available
        
    Returns:
        DocumentProcessingError instance
    """
    return DocumentProcessingError(
        message=message,
        file_id=file_id,
        step=step,
        original_exception=original_exception
    )

# log_processing_step 函数用于记录文档处理的每个步骤，提供了结构化的日志信息，包括文件ID、处理步骤和日志消息。
def log_processing_step(file_id: str, step: ProcessingStep, message: str) -> None:
    """
    Log a processing step with structured context.
    
    Args:
        file_id: File ID for context
        step: Current processing step
        message: Log message
    """
    logger.info(
        f"Processing step {step.value} for file {file_id}: {message}",
        extra={
            "file_id": file_id,
            "step": step.value,
            "step_message": message
        }
    )

# log_processing_success 函数用于记录文档处理成功完成的情况，提供了处理时间、文档数量和总令牌数等指标，以便进行性能监控和分析。
def log_processing_success(file_id: str, processing_time: float, document_count: int, total_tokens: int) -> None:
    """
    Log successful processing completion with metrics.
    
    Args:
        file_id: File ID for context
        processing_time: Total processing time in seconds
        document_count: Number of documents created
        total_tokens: Total tokens processed
    """
    logger.info(
        f"Document processing completed successfully for file {file_id}",
        extra={
            "file_id": file_id,
            "processing_time": processing_time,
            "document_count": document_count,
            "total_tokens": total_tokens,
            "status": "completed"
        }
    )
