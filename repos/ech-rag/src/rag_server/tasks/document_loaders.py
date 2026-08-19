'''该模块通过统一的解析器方法提供文档加载功能。
    它支持多种文件格式，并配备专用解析器以实现最佳内容提取。
    关键组件:
    使用GenericLoader.from_filesystem的统一文档加载器工厂
    基于内容类型的专用解析器选择
    对于不支持的内容类型提供回退机制
    支持PDF、文本、Markdown、Word、HTML及其他文件格式
    对加载失败提供全面的错误处理机制
    支持的文件类型:
    PDF:用于可靠PDF文本提取的PDFMiner解析器
    文本/Markdown:用于纯文本和Markdown 文件的TextParser
    文档:Docx2txtLoader用于.docx文件(直接加载器，非通过GenericLoader)
    HTML:BS4HTMLParser用于提取HTML内容其他:基于MIME类型解析器，带TextParser回退机制'''
import os
from typing import Any, List, Union

from langchain_community.document_loaders.parsers import BS4HTMLParser, PDFMinerParser
from langchain_community.document_loaders.parsers.generic import MimeTypeBasedParser
from langchain_community.document_loaders.parsers.txt import TextParser
from langchain_community.document_loaders.generic import GenericLoader

from ..logging_config import get_logger
from .document_processing_errors import DocumentProcessingError, ProcessingStep
from .document_processing_types import (
    DocumentLoader as DocumentLoaderProtocol,
    ParserInfo,
    SUPPORTED_CONTENT_TYPES,
    PARSER_MAPPING
)

logger = get_logger(__name__)

def get_document_loader(file_path: str, content_type: str, file_id: str) -> Union[GenericLoader, Any]:
    """
    根据内容类型使用统一解析器方法获取适当的文档加载器。
    该函数会创建一个带有相应解析器的加载器实例，用于处理指定的内容类型。大多数文件类型均采用“GenericLoader.from_filesystem”模式，
    但某些文件类型(如Word文档)则需要专门的加载器。
    参数:
    file_path:要加载的文件路径content_type:文件的MIME类型
    file_id:用于错误报告和日志记录的文件ID
    返回值:
    为文件类型配置的加载器实例(通用加载器或专用加载器)
    抛出:
    DocumentProcessingError:对于不支持的内容类型或加载器创建失败时抛出
    """
    try:
        file_name = os.path.basename(file_path)
        
        # Word documents need specialized loaders (MsWordParser doesn't work with GenericLoader blobs)
        # 如果内容类型是Word文档，则使用专用加载器
        if content_type in [
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ]:
            return _get_word_document_loader(file_path, content_type, file_id)
        
        # For other file types, use GenericLoader with appropriate parser
        file_dir = os.path.dirname(file_path)
        
        # Select appropriate parser based on content type
        # 否则，根据内容类型选择适当的解析器
        parser = _get_parser_for_content_type(content_type, file_id)
        
        # Create GenericLoader with the selected parser
        loader = GenericLoader.from_filesystem(
            path=file_dir,
            glob=file_name,
            parser=parser,
            show_progress=False
        )
        
        logger.debug(f"Created document loader for {content_type} file: {file_name}")
        return loader
        
    except Exception as e:
        if isinstance(e, DocumentProcessingError):
            raise
        raise DocumentProcessingError(
            f"Error creating document loader for {content_type}: {str(e)}",
            file_id,
            ProcessingStep.EXTRACTING_CONTENT,
            e
        ) from e

def _get_word_document_loader(file_path: str, content_type: str, file_id: str) -> Any:
    """
    为Word文档获取合适的加载器。
    Word文档需要专用的加载器，因为MsWordParser无法与GenericLoader的blob机制正确工作。
    优先级顺序:2.Docx2txtLoader一轻量级替代方案(需要docx2txt包)
    1.UnstructuredWordDocumentLoader- 适用于未结构化[docx]文件(已安装)
    参数:
    file_path:Word文档的路径
    content_type:文件的MIME类型
    file_id:用于错误报告的文件ID
    返回值:
    Word文档的加载器实例
    抛出异常
    DocumentProcessingError:如果未找到合适的加载器
    """
    file_name = os.path.basename(file_path)
    errors = []
    
    # Try UnstructuredWordDocumentLoader first (handles both .doc and .docx)
    # This should work since we have unstructured[docx] installed
    try:
        from langchain_community.document_loaders import UnstructuredWordDocumentLoader
        logger.debug(f"Using UnstructuredWordDocumentLoader for Word document {file_id}: {file_name}")
        return UnstructuredWordDocumentLoader(file_path)
    except ImportError as e:
        errors.append(f"UnstructuredWordDocumentLoader import failed: {e}")
        logger.warning(f"UnstructuredWordDocumentLoader not available for {file_id}: {e}")
    except Exception as e:
        errors.append(f"UnstructuredWordDocumentLoader error: {e}")
        logger.warning(f"UnstructuredWordDocumentLoader failed for {file_id}: {e}")
    
    # Try Docx2txtLoader as fallback for .docx files (requires docx2txt package)
    # 尝试使用Docx2txtLoader作为.docx文件的回退方案(需要docx2txt包)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            from langchain_community.document_loaders import Docx2txtLoader
            logger.debug(f"Using Docx2txtLoader for .docx file {file_id}: {file_name}")
            return Docx2txtLoader(file_path)
        except ImportError as e:
            errors.append(f"Docx2txtLoader import failed: {e}")
            logger.warning(f"Docx2txtLoader not available for {file_id}: {e}")
        except Exception as e:
            errors.append(f"Docx2txtLoader error: {e}")
            logger.warning(f"Docx2txtLoader failed for {file_id}: {e}")
    
    # No loader available
    error_details = "; ".join(errors)
    raise DocumentProcessingError(
        f"No suitable Word document loader available. Tried loaders failed: {error_details}. "
        f"Ensure unstructured[docx] is properly installed or install docx2txt: pip install docx2txt",
        file_id,
        ProcessingStep.EXTRACTING_CONTENT
    )


def _get_parser_for_content_type(content_type: str, file_id: str) -> Any:
    """
    得到适当的解析器基于内容类型，用于与GenericLoader一起使用。
    该函数为每种内容类型选择最合适的解析器，为最佳内容提取提供专门的解析能力。
    注意:Word文档由_get_word_document_loader()单独处理，因为它们需要专门的加载器，而不是GenericLoader + 解析器。
    参数:
    content_type:文件的MIME类型
    file_id:用于错误报告的文件ID
    返回值:
    给定内容类型的解析器实例
    抛出:
    DocumentProcessingError:对于解析器创建失败
    """

    try:
        if content_type == "application/pdf":
            # Use PDFMinerParser for PDF files - provides reliable text extraction
            logger.debug(f"Selected PDFMinerParser for PDF file {file_id}")
            return PDFMinerParser()
            
        elif content_type in ["text/plain", "text/markdown"]:
            # Use TextParser for text and markdown files - handles UTF-8 encoding
            logger.debug(f"Selected TextParser for text/markdown file {file_id}")
            return TextParser()
            
        elif content_type in [
            "text/html",
            "application/xhtml+xml"
        ]:
            # Use BS4HTMLParser for HTML files - extracts text from HTML structure
            logger.debug(f"Selected BS4HTMLParser for HTML file {file_id}")
            return BS4HTMLParser()
            
        else:
            # Use MimeTypeBasedParser as fallback for other file types
            logger.debug(f"Using MimeTypeBasedParser fallback for content type {content_type} (file {file_id})")
            try:
                return MimeTypeBasedParser()
            except Exception as fallback_error:
                # If MimeTypeBasedParser fails, fall back to TextParser
                logger.warning(
                    f"MimeTypeBasedParser failed for {content_type} (file {file_id}), "
                    f"using TextParser as final fallback: {fallback_error}"
                )
                return TextParser()
                
    except Exception as e:
        raise DocumentProcessingError(
            f"Error creating parser for content type {content_type}: {str(e)}",
            file_id,
            ProcessingStep.EXTRACTING_CONTENT,
            e
        ) from e


def get_supported_content_types() -> List[str]:
    """
    Get list of supported content types.

    Returns:
        List of supported MIME types
    """
    return SUPPORTED_CONTENT_TYPES


def is_content_type_supported(content_type: str) -> bool:
    """
    Check if a content type is explicitly supported.
    
    Args:
        content_type: MIME type to check
        
    Returns:
        True if content type is explicitly supported, False otherwise
        
    Note:
        Unsupported content types will still be processed using fallback parsers
    """
    return content_type in get_supported_content_types()

# 得到解析器信息
def get_parser_info(content_type: str) -> ParserInfo:
    """
    Get information about the parser that would be used for a content type.

    Args:
        content_type: MIME type to get parser info for

    Returns:
        ParserInfo object with parser information including name and description
    """
    if content_type == "application/pdf":
        return ParserInfo(
            parser="PDFMinerParser",
            description="Specialized PDF text extraction with reliable formatting"
        )
    elif content_type in ["text/plain", "text/markdown"]:
        return ParserInfo(
            parser="TextParser",
            description="Plain text parser with UTF-8 encoding support"
        )
    elif content_type in [
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]:
        return ParserInfo(
            parser="MsWordParser",
            description="Microsoft Word document parser for .doc and .docx files"
        )
    elif content_type in ["text/html", "application/xhtml+xml"]:
        return ParserInfo(
            parser="BS4HTMLParser",
            description="HTML parser using BeautifulSoup for text extraction"
        )
    else:
        return ParserInfo(
            parser="MimeTypeBasedParser (fallback to TextParser)",
            description="Generic parser with text fallback for unsupported types"
        )
