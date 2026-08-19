"""
Type definitions for document processing modules.

This module provides specific type definitions to replace generic 'Any' types
throughout the document processing pipeline, improving type safety and code clarity.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple, Union
from uuid import UUID

from langchain_core.documents import Document


@dataclass
class ChunkData:
    """Data structure for document chunks ready for database storage."""
    id: UUID
    file_id: UUID
    collection_id: UUID
    chunk_id: str
    content: str
    character_count: int
    token_count: int
    chunk_index: int
    document_type: str
    metadata: Dict[str, Union[str, int, float, bool]]


@dataclass
class FileInfo:
    """File information container for session-safe operations."""
    id: UUID
    project_id: UUID
    collection_id: Optional[UUID]
    language: Optional[str]
    storage_path: str
    content_type: str
    original_filename: str


@dataclass
class ProcessingResult:
    """Document processing result container."""
    status: str
    file_id: str
    document_count: int
    total_tokens: int
    processing_time: float
    error: Optional[str] = None


@dataclass
class ChunkingStats:
    """Statistics for document chunking operations."""
    total_chunks: int
    total_characters: int
    total_tokens: int
    avg_chunk_size: int
    avg_tokens_per_chunk: int
    min_chunk_size: int
    max_chunk_size: int


@dataclass
class EmbeddingStats:
    """Statistics for embedding generation operations."""
    total_embeddings: int
    dimensions: int
    total_values: int
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    avg_value: Optional[float] = None


@dataclass
class EmbeddingServiceInfo:
    """Information about the embedding service configuration."""
    provider: str
    model: str
    dimensions: int
    error: Optional[str] = None


@dataclass
class ParserInfo:
    """Information about document parser configuration."""
    parser: str
    description: str


# Type aliases for better readability
DocumentList = List[Document]
ChunkDataList = List[ChunkData]
EmbeddingVector = List[float]
EmbeddingList = List[EmbeddingVector]
MetadataDict = Dict[str, Union[str, int, float, bool]]
DocumentTuple = Tuple[UUID, str, Optional[MetadataDict]]
DocumentTupleList = List[DocumentTuple]
SearchResult = Tuple[str, float, MetadataDict]
SearchResultList = List[SearchResult]


class DocumentLoader(Protocol):
    """Protocol for document loaders."""
    
    def load(self) -> DocumentList:
        """Load documents from source."""
        ...


class TextSplitter(Protocol):
    """Protocol for text splitters."""
    
    def split_documents(self, documents: DocumentList) -> DocumentList:
        """Split documents into chunks."""
        ...
    
    def split_text(self, text: str) -> List[str]:
        """Split text into chunks."""
        ...


class EmbeddingService(Protocol):
    """Protocol for embedding services."""
    
    async def generate_embedding(self, text: str) -> EmbeddingVector:
        """Generate embedding for single text."""
        ...
    
    async def generate_embeddings_batch(self, texts: List[str]) -> EmbeddingList:
        """Generate embeddings for multiple texts."""
        ...
    
    def get_embedding_provider(self) -> str:
        """Get embedding provider name."""
        ...
    
    def get_embedding_model(self) -> str:
        """Get embedding model name."""
        ...
    
    def get_embedding_dimensions(self) -> int:
        """Get embedding dimensions."""
        ...


class VectorStoreService(Protocol):
    """Protocol for vector store services."""
    
    async def add_documents_batch(self, documents: DocumentTupleList) -> List[str]:
        """Add multiple documents to vector store."""
        ...
    
    async def similarity_search(
        self,
        query: str,
        k: int = 10,
        filter_dict: Optional[MetadataDict] = None,
        score_threshold: Optional[float] = None
    ) -> SearchResultList:
        """Perform similarity search."""
        ...
    
    async def delete_document_embedding(self, document_id: UUID) -> bool:
        """Delete document embedding."""
        ...


# Content type constants
SUPPORTED_CONTENT_TYPES = [
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/html",
    "application/xhtml+xml"
]

# Parser mapping
PARSER_MAPPING = {
    "application/pdf": "PDFMinerParser",
    "text/plain": "TextParser",
    "text/markdown": "TextParser",
    "application/msword": "MsWordParser",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "MsWordParser",
    "text/html": "BS4HTMLParser",
    "application/xhtml+xml": "BS4HTMLParser"
}

# Default values
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_EMBEDDING_DIMENSIONS = 1536
DEFAULT_SEARCH_RESULTS = 10
