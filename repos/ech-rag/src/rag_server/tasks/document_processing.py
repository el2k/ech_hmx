"""
用于文件上传和内容提取的文档处理任务。
该模块提供文档处理的主要Celery任务接口，通过模块化组件协调完整的文档处理流程。
处理管道包括:
从多种格式(PDF、Word、文本、Markdown、HTML)中提取文件内容
文档分块以实现最佳RAG性能
用于语义搜索的向量嵌入生成
带有适当会话管理的数据库持久化
全面的错误处理与恢复
性能监控与日志记录
架构:
模块化设计，遵循单一职责原则
基于统一解析器的文档加载
可配置的分块与嵌入策略
支持多提供商嵌入(OpenAI、千问)
带有详细上下文的稳健错误处理
实时进度跟踪与状态更新
该模块作为Celery任务的主要入口点，同时将特定功能委托给专用模块以提高可维护性。
"""
from typing import Any, Dict
from uuid import UUID

from .celery_app import celery_app
from .document_processing_core import process_file_async
from .document_processing_errors import ProcessingStatus
from ..config import get_settings
from ..logging_config import get_logger

# Configure logger with structured formatting
logger = get_logger(__name__)
settings = get_settings()

@celery_app.task(bind=True, name="process_file_task")
def process_file_task(
    self,
    file_id: str,
    collection_id: str,
    is_qa_mode: bool = settings.default_is_qa_mode
) -> Dict[str, Any]:
    """
    celery任务，用于处理上传的文件。
    这个任务协调完整的文档处理管道:
    1. 加载和验证文件信息
    2. 使用适当的文档加载器提取内容
    3. 对文档进行分块，以实现最佳嵌入大小
    4. 使用配置的嵌入服务生成嵌入
    5. 将文档和嵌入存储在数据库中
    6. 更新文件状态和指标
    参数:
        file_id: 要处理的文件的UUID字符串
        collection_id: 文件所属集合的UUID字符串
    返回:
        包含处理结果和指标的字典
    """
    import asyncio
    from uuid import UUID
    from ..database import reset_db_state
    from .document_processing_core import update_website_page_status_by_file_id

    try:
        # Convert string IDs to UUIDs
        file_uuid = UUID(file_id)
        collection_uuid = UUID(collection_id)

        # Reset database state before creating new event loop
        # This prevents 'Future attached to a different loop' errors
        reset_db_state()

        # Run the async processing function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(
                process_file_async(file_uuid, collection_uuid, self.request.id, is_qa_mode)
            )
            # Convert ProcessingResult to dictionary for JSON serialization
            return {
                "status": result.status,
                "file_id": result.file_id,
                "document_count": result.document_count,
                "total_tokens": result.total_tokens,
                "processing_time": result.processing_time,
                "error": result.error
            }
        finally:
            # Clean up database connections before closing the loop
            reset_db_state()
            loop.close()

    except Exception as e:
        logger.error(f"Task execution failed for file {file_id}: {e}")

        # Update WebsitePage status if this file came from crawling
        # This ensures pages don't get stuck in "processing" state
        try:
            reset_db_state()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    update_website_page_status_by_file_id(file_id, "failed", str(e))
                )
            finally:
                reset_db_state()
                loop.close()
        except Exception as status_error:
            logger.error(f"Failed to update page status for file {file_id}: {status_error}")

        return {
            "status": ProcessingStatus.FAILED.value,
            "file_id": file_id,
            "document_count": 0,
            "total_tokens": 0,
            "processing_time": 0,
            "error": str(e)
        }
