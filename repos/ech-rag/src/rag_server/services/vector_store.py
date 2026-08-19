"""
Vector store service using langchain-postgres for vector operations.
"""

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.exc import ProgrammingError
from langchain_postgres import PGEngine, PGVectorStore
from langchain_core.documents import Document
from langchain_postgres.v2.vectorstores import DistanceStrategy
from langchain_postgres.v2.hybrid_search_config import (
    HybridSearchConfig,
    reciprocal_rank_fusion,
)
from sqlalchemy import create_engine

from ..config import get_settings
from ..database import get_db_session
from ..logging_config import get_logger
from ..models import FileDocument
from .embedding import get_embedding_service

logger = get_logger(__name__)

TABLE_NAME = FileDocument.table_name
ID_COLUMN = "id"
CONTENT_COLUMN = "content"
METADATA_COLUMNS = ["file_id", "collection_id", "project_id"]
VECTOR_SIZE = 1536
'''这段代码是在实现一个异步的文本嵌入（Embedding）生成方法。
简单来说，它的作用就是把一段文本（比如一句话或一个词）转换成计算机能理解的浮点数向量（List[float]）。
这种向量通常用于语义搜索、文本相似度计算或作为大语言模型（LLM）的上下文输入。
为了让这个过程在异步环境（如高并发 Web 服务）中不卡顿，它做了以下几件核心的事情：
异步包装阻塞操作：底层的嵌入模型调用通常是同步且耗时的（需要等待网络请求或本地计算）。
代码使用 loop.run_in_executor 把这个耗时操作丢给线程池去跑，从而释放主事件循环，保证系统的高并发响应能力。
兼容不同版本的客户端：通过 self._compat_mode 判断，代码支持两种不同的底层调用方式。
如果是兼容模式，就调用备用的 _compat_make_embeddings_request 方法并提取第一个结果；如果是标准模式，就直接调用 _client.embed_query。
结果校验与返回：对底层返回的结果进行校验，如果拿不到向量数据就会抛出异常，确保上层调用者能拿到有效的 List[float] 向量。'''

# 向量化搜索的隔离维度是"项目"而非"用户"。
class VectorStoreService:
    def __init__(self):
        self.settings = get_settings()
        self.embedding_service = get_embedding_service()
        # PGVectorStore 是一个用于向量存储和检索的类，它封装了与 PostgreSQL 数据库的交互逻辑，提供了向量化数据的存储、查询和管理功能。
        self._vector_store: Optional[PGVectorStore] = None
        self._vector_stores: dict[str, PGVectorStore] = {}
        # PGEngine 是一个用于与 PostgreSQL 数据库进行交互的类，它提供了连接管理、查询执行和事务处理等功能。
        self._pg_engine: Optional[PGEngine] = None
        self._hybrid_search_config = None

    def _create_hybrid_search_config(self) -> HybridSearchConfig:
        return HybridSearchConfig(
            tsv_column= f"{CONTENT_COLUMN}_tsv",
            tsv_lang = "pg_catalog.english",
            # reciprocal_rank_fusion 是一种用于混合搜索的排序融合方法，它通过对不同搜索结果的排名进行加权平均，从而生成一个综合的排序结果。
            fusion_function=reciprocal_rank_fusion,
            # rrf_k 是 reciprocal_rank_fusion 方法中的一个参数，表示在计算综合排名时，考虑的前 k 个搜索结果的排名信息。较大的 rrf_k 值会使得更多的搜索结果对最终排名产生影响，从而可能提高搜索的准确性，但也会增加计算复杂度。
            # fetch_top_k 是在执行混合搜索时，从每个单独的搜索结果中获取的前 k 个结果的数量。这个参数用于控制在进行融合排序之前，每个搜索源返回的候选结果的数量。较大的 fetch_top_k 值会增加搜索的覆盖范围，但也可能引入更多的噪声，从而影响最终
            fusion_function_parameters={
                "rrf_k": 60,
                "fetch_top_k": 20,
            },
        )

    async def get_vector_store(self) -> PGVectorStore:
        if self._vector_store is None:
            sync_db_url = self.settings.database_url
            self._pg_engine = PGEngine.from_connection_string(sync_db_url)
            self._hybrid_search_config = self._create_hybrid_search_config()
            try:
                self._pg_engine.init_vectorstore_table(
                    table_name=TABLE_NAME,
                    id_column=ID_COLUMN,
                    content_column=CONTENT_COLUMN,
                    metadata_columns=METADATA_COLUMNS,
                    vector_size=VECTOR_SIZE,
                    hybrid_search_config=self._hybrid_search_config,
                )
            except ProgrammingError as e:
                logger.error(f"Error initializing vector store table: {str(e)}")
            self._vector_store = await PGVectorStore.create(
                            engine=self._pg_engine,
                            embedding_service=self.embedding_service.embeddings_client,
                            id_column=ID_COLUMN,
                            metadata_columns=METADATA_COLUMNS,
                            content_column=CONTENT_COLUMN,
                            table_name=TABLE_NAME,
                            distance_strategy=DistanceStrategy.COSINE_DISTANCE,
                            hybrid_search_config=self._hybrid_search_config,
            )
            return self._vector_store
    # 按项目隔离的批量入库，使用项目专属的 embedding 客户端
    async def get_vector_store_for_project(self, project_key: str, embeddings_client: Any) -> PGVectorStore:
        if self._pg_engine is None:
                    sync_db_url = self.settings.database_url
                    self._pg_engine = PGEngine.from_connection_string(sync_db_url)
                    self._hybrid_search_config = self._create_hybrid_search_config()
                    try:
                        self._pg_engine.init_vectorstore_table(
                            table_name=TABLE_NAME,
                            id_column=ID_COLUMN,
                            content_column=CONTENT_COLUMN,
                            metadata_columns=METADATA_COLUMNS,
                            vector_size=VECTOR_SIZE,
                            hybrid_search_config=self._hybrid_search_config,
                        )
                    except ProgrammingError as e:
                        print(f"Table already exists. Skipping creation.{str(e)}")
        # Create per-project store if missing
        if project_key not in self._vector_stores:
            self._vector_stores[project_key] = await PGVectorStore.create(
                engine=self._pg_engine,
                embedding_service=embeddings_client,
                id_column=ID_COLUMN,
                metadata_columns=METADATA_COLUMNS,
                content_column=CONTENT_COLUMN,
                table_name=TABLE_NAME,
                distance_strategy=DistanceStrategy.COSINE_DISTANCE,
                hybrid_search_config=self._hybrid_search_config,
            )

        return self._vector_stores[project_key]    
    # add_documents_batch_for_project 方法的作用是将一批文档添加到指定项目的向量存储中。它接收一个包含文档信息的列表、项目的唯一标识符（project_key）以及用于生成嵌入向量的客户端（embeddings_client）。
    # 该方法首先获取或创建与项目相关联的向量存储实例，然后将每个文档的内容转换为嵌入向量，并将这些向量与文档的元数据一起存储到数据库中。最终，它返回一个包含所有已添加文档 ID 的列表，以便调用者可以跟踪这些文档在向量存储中的状态。           
    async def add_documents_batch_for_project(
        self,
        documents: List[Tuple[UUID, str, Optional[Dict[str, Any]]]],
        project_key: str,
        embedding_client: Any,
    ) -> List[str]:
        if not documents:
            return []
        try:
            vector_store = await self.get_vector_store_for_project(project_key, embedding_client)
            max_batch_size = min(self.settings.embedding_batch_size, 10)
            logger.info(f"Processing {len(documents)} documents in batches of {max_batch_size} for project {project_key}")
            all_vector_ids: List[str] = []
            total_batches = (len(documents) + max_batch_size - 1) // max_batch_size
            # asyncio.get_event_loop() 获取当前的事件循环对象。事件循环是异步编程的核心，它负责调度和执行异步任务。
            import asyncio
            loop = asyncio.get_event_loop()

            for batch_idx in range(0, len(documents), max_batch_size):
                batch_documents = documents[batch_idx:batch_idx + max_batch_size]
                batch_num = (batch_idx // max_batch_size) + 1
                logger.debug(f"Processing batch {batch_num}/{total_batches} with {len(batch_documents)} documents for project {project_key}")
                # document_ids 指的是从当前批次的文档中提取每个文档的唯一标识符（ID），这些 ID 通常用于在数据库或向量存储中跟踪和管理文档。通过列表推导式 [doc[0] for doc in batch_documents]，代码遍历 batch_documents 列表中的每个文档元组，并提取每个元组的第一个元素（即文档的 ID），最终生成一个包含所有文档 ID 的列表 document_ids。
                document_ids = [doc[0] for doc in batch_documents]
                contents = [doc[1] for doc in batch_documents]
                metadatas: List[Dict[str, Any]] = []
                for doc_id, content, metadata in batch_documents:
                    doc_metadata = metadata or {}
                    doc_metadata.update({
                        "document_id": str(doc_id),
                        "content_length": len(content),
                    })
                    metadatas.append(doc_metadata)
                # vector_ids 这里主要是为了 将文档内容转换为向量表示，并将这些向量与文档的元数据一起存储到向量存储中。通过调用 vector_store.add_texts 方法，代码将当前批次的文档内容（contents）、对应的元数据（metadatas）以及文档 ID（document_ids）传递给向量存储。这个方法会返回一个包含所有已添加文档 ID 的列表 vector_ids，这些 ID 可以用于后续的检索或管理操作。
                try:
                    # run_in_executor 方法的作用是将一个阻塞的操作（在这里是向量存储的添加操作）放到一个单独的线程或进程中执行，从而避免阻塞主事件循环。它接收三个参数：
                    # executor: 指定要使用的执行器。如果为 None，则使用默认的线程池执行器。
                    # func: 要执行的函数。在这里，使用了一个 lambda 函数来包装 vector_store.add_texts 方法的调用。
                    # *args: 传递给 func 的参数。在这里，传递了 texts、metadatas 和 ids。
                    # 这个函数的返回值是一个协程对象，表示异步操作的结果。通过 await 关键字，代码会等待这个协程完成，并获取其返回值（即 vector_ids）。
                    # vector_ids 是一个列表，包含了所有已添加文档的唯一标识符（ID）。这些 ID 可以用于后续的检索、更新或删除操作。通过将这些 ID 存储在 all_vector_ids 列表中，代码可以在整个批处理过程中跟踪所有已处理的文档。
                    vector_ids = await loop.run_in_executor(
                        None,
                        lambda: vector_store.add_texts(
                            texts=contents,
                            metadatas=metadatas,
                            ids=[str(doc_id) for doc_id in document_ids],
                        )
                    )
                    all_vector_ids.extend(vector_ids)
                    logger.debug(f"Successfully processed batch {batch_num}/{total_batches} for project {project_key}")
                except Exception as batch_error:
                    logger.error(f"Failed to process batch {batch_num}/{total_batches} for project {project_key}: {str(batch_error)}")
                    all_vector_ids.extend([""] * len(batch_documents))

            logger.info(f"Completed batch processing for project {project_key}: {len(all_vector_ids)} total documents processed")
            return all_vector_ids

        except Exception as e:
            logger.error(f"Failed to add document embeddings batch for project {project_key}: {str(e)}")
            raise    
    # 添加单个文档的嵌入向量到向量存储中。它接收文档的唯一标识符（document_id）、文档内容（content）以及可选的元数据（metadata）。
    async def add_document_embedding(
            self,
            document_id: UUID,
            content: str,
            metadata: Optional[Dict[str, Any]] = None
        ) -> str:
            """
            Add a document embedding to the vector store.
    
            Args:
                document_id: UUID of the document
                content: Document content to embed
                metadata: Optional metadata to store with the embedding
    
            Returns:
                Vector ID in the vector store
    
            Raises:
                Exception: If embedding generation or storage fails
            """
            try:
                # Generate embedding
                embedding = await self.embedding_service.generate_embedding(content)
    
                # Prepare metadata
                doc_metadata = metadata or {}
                doc_metadata.update({
                    "document_id": str(document_id),
                    "content_length": len(content),
                })
    
                # Add to vector store
                vector_store = await self.get_vector_store()
    
                # Run synchronous operation in thread pool
                import asyncio
                loop = asyncio.get_event_loop()
                vector_ids = await loop.run_in_executor(
                    None,
                    lambda: vector_store.add_texts(
                        texts=[content],
                        metadatas=[doc_metadata],
                        ids=[str(document_id)]
                    )
                )
    
                vector_id = vector_ids[0] if vector_ids else str(document_id)
    
                # Update document record with embedding info
                await self._update_document_embedding_info(
                    document_id,
                    embedding
                )
    
                logger.info(f"Added embedding for document {document_id}")
                return vector_id
    
            except Exception as e:
                logger.error(f"Failed to add document embedding {document_id}: {str(e)}")
                raise        

    # 批量添加文档嵌入向量到向量存储中，支持自动批处理和错误处理。它接收一个包含文档信息的列表，每个文档信息包括文档的唯一标识符（UUID）、文档内容（字符串）以及可选的元数据（字典）。
    async def add_documents_batch(
            self,
            documents: List[Tuple[UUID, str, Optional[Dict[str, Any]]]]
        ) -> List[str]:
            """
            Add multiple document embeddings in batch with automatic batch size management.
    
            This method automatically splits large batches into smaller chunks to respect
            API limitations (e.g., Qwen3 API limit of 10 documents per batch).
    
            Args:
                documents: List of (document_id, content, metadata) tuples
    
            Returns:
                List of vector IDs in the vector store
    
            Raises:
                Exception: If batch processing fails
            """
            if not documents:
                return []
    
            try:
                # Get batch size from settings, with a maximum of 10 for Qwen3 compatibility
                max_batch_size = min(self.settings.embedding_batch_size, 10)
                logger.info(f"Processing {len(documents)} documents in batches of {max_batch_size}")
    
                all_vector_ids = []
                total_batches = (len(documents) + max_batch_size - 1) // max_batch_size
    
                # Process documents in batches
                for batch_idx in range(0, len(documents), max_batch_size):
                    batch_documents = documents[batch_idx:batch_idx + max_batch_size]
                    batch_num = (batch_idx // max_batch_size) + 1
                    logger.debug(f"Processing batch {batch_num}/{total_batches} with {len(batch_documents)} documents")
    
                    try:
                        # Process single batch
                        batch_vector_ids = await self._process_single_batch(batch_documents)
                        all_vector_ids.extend(batch_vector_ids)
    
                        logger.debug(f"Successfully processed batch {batch_num}/{total_batches}")
    
                    except Exception as batch_error:
                        logger.error(f"Failed to process batch {batch_num}/{total_batches}: {str(batch_error)}")
                        # Continue with other batches instead of failing completely
                        # Add empty strings as placeholders for failed batch
                        all_vector_ids.extend([""] * len(batch_documents))
    
                logger.info(f"Completed batch processing: {len(all_vector_ids)} total documents processed")
                return all_vector_ids
    
            except Exception as e:
                logger.error(f"Failed to add document embeddings batch: {str(e)}")
                raise
    # _process_single_batch 方法的作用是处理一批文档，将它们的内容转换为向量表示，并将这些向量与文档的元数据一起存储到向量存储中。
    # 它接收一个包含文档信息的列表，每个文档信息包括文档的唯一标识符（UUID）、文档内容（字符串）以及可选的元数据（字典）。
    async def _process_single_batch(
            self,
            batch_documents: List[Tuple[UUID, str, Optional[Dict[str, Any]]]]
        ) -> List[str]:
            """
            Process a single batch of documents.
    
            Args:
                batch_documents: List of (document_id, content, metadata) tuples for this batch
    
            Returns:
                List of vector IDs for this batch
    
            Raises:
                Exception: If batch processing fails
            """
            # Extract data for batch processing
            document_ids = [doc[0] for doc in batch_documents]
            contents = [doc[1] for doc in batch_documents]
            metadatas = []
    
            for doc_id, content, metadata in batch_documents:
                doc_metadata = metadata or {}
                doc_metadata.update({
                    "document_id": str(doc_id),
                    "content_length": len(content),
                })
                metadatas.append(doc_metadata)
    
            # Add to vector store
            vector_store = await self.get_vector_store()
    
            # Run synchronous operation in thread pool
            import asyncio
            loop = asyncio.get_event_loop()
    
            print("contents--->",len(contents))
            vector_ids = await loop.run_in_executor(
                None,
                lambda: vector_store.add_texts(
                    texts=contents,
                    metadatas=metadatas,
                    ids=[str(doc_id) for doc_id in document_ids]
                )
            )
    
            return vector_ids
    # similarity_search 方法的作用是在向量存储中执行相似性搜索。它接收一个查询文本（query）、返回结果的数量（k）、可选的元数据过滤器（filter_dict）以及可选的相似度分数阈值（score_threshold）。
    async def similarity_search(
            self,
            query: str,
            k: int = 10,
            filter_dict: Optional[Dict[str, Any]] = None,
            score_threshold: Optional[float] = None
        ) -> list[tuple[Document, float]]:
            """
            Perform similarity search in the vector store.
    
            Args:
                query: Search query text
                k: Number of results to return
                filter_dict: Optional metadata filters
                score_threshold: Minimum similarity score threshold
    
            Returns:
                List of (content, score, metadata) tuples
    
            Raises:
                Exception: If search fails
            """
            try:
                vector_store = await self.get_vector_store()
                # Run synchronous operation in thread pool
                import asyncio
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None,
                    lambda: vector_store.similarity_search_with_score(
                        query=query,
                        k=k,
                        filter=filter_dict
                    )
                )
    
    
                # Step 1: Filter and Convert distance to similarity (1 - score)
                # langchain-postgres returns distance (smaller is better, 0.0 is perfect)
                # We want similarity (higher is better, 1.0 is perfect)
                new_results = []
                for doc, score in results:
                    if score is not None:
                        # Convert distance to similarity
                        similarity = max(0.0, min(1.0, 1.0 - float(score)))
                        
                        # Apply threshold filtering on similarity
                        if score_threshold is not None and score_threshold > 0:
                            if similarity < score_threshold:
                                continue
                                
                        new_results.append((doc, similarity))
    
                # Step 2: Explicitly sort by similarity DESCENDING (highest similarity first)
                new_results.sort(key=lambda x: x[1], reverse=True)
    
                logger.debug(f"Similarity search returned {len(new_results)} results")
                return new_results
    
            except Exception as e:
                logger.error(f"Similarity search failed: {str(e)}")
                raise
    
    
    async def similarity_search_for_project(
        self,
        query: str,
        project_key: str,
        embeddings_client: Any,
        k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None,
    ) -> list[tuple[Document, float]]:
        """
        Perform similarity search using a vector store bound to the project's
        embedding configuration.

        Args:
            query: Search query text
            project_key: Project identifier (e.g., project_id as string)
            embeddings_client: Embedding client configured for the project
            k: Number of results to return
            filter_dict: Optional metadata filters
            score_threshold: Minimum similarity score threshold

        Returns:
            List of (Document, score) tuples
        """
        try:
            # Use per-project vector store bound to the provided embedding client
            # 这里的 get_vector_store_for_project 方法是为了获取与特定项目相关联的向量存储实例。
            # 每个项目可能有不同的嵌入配置（例如使用不同的嵌入模型或参数），因此需要为每个项目创建或获取一个独立的向量存储。
            vector_store = await self.get_vector_store_for_project(project_key, embeddings_client)
            # Run synchronous operation in thread pool
            import asyncio
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: vector_store.similarity_search_with_score(
                    query=query,
                    k=k,
                    filter=filter_dict,
                ),
            )

            # Step 1: Filter and Convert distance to similarity (1 - score)
            new_results = []
            for doc, score in results:
                if score is not None:
                    # Convert distance to similarity
                    similarity = max(0.0, min(1.0, 1.0 - float(score)))
                    
                    # Apply threshold filtering on similarity
                    if score_threshold is not None and score_threshold > 0:
                        if similarity < score_threshold:
                            continue
                            
                    new_results.append((doc, similarity))

            # Step 2: Explicitly sort by similarity DESCENDING (highest similarity first)
            new_results.sort(key=lambda x: x[1], reverse=True)

            return new_results
        except Exception as e:
            logger.error(f"Similarity search (per-project) failed: {str(e)}")
            raise
    
    async def delete_document_embedding(self, document_id: UUID) -> bool:
        """
        Delete a document embedding from the vector store.

        Args:
            document_id: UUID of the document to delete

        Returns:
            True if deletion was successful, False otherwise
        """
        try:
            vector_store = await self.get_vector_store()

            # Run synchronous operation in thread pool
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: vector_store.delete(ids=[str(document_id)])
            )

            logger.info(f"Deleted embedding for document {document_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete document embedding {document_id}: {str(e)}")
            return False
    # 更新文档记录的嵌入信息，包括嵌入向量、使用的嵌入模型和嵌入维度。它接收文档的唯一标识符（document_id）和生成的嵌入向量（embedding）。
    async def _update_document_embedding_info(
        self,
        document_id: UUID,
        embedding: List[float]
    ) -> None:
        """
        Update document record with embedding information.

        Args:
            document_id: Document UUID
            embedding: Embedding vector
        """
        try:
            # Import here to avoid circular imports
            from ..database import async_session_factory, create_session_factory
            from sqlalchemy import update, select

            # Ensure session factory is initialized
            if async_session_factory is None:
                create_session_factory()

            # Use session factory directly to avoid context manager issues in Celery
            async with async_session_factory() as db:
                try:
                    # First check if document exists
                    result = await db.execute(
                        select(FileDocument).where(FileDocument.id == document_id)
                    )
                    document = result.scalar_one_or_none()

                    if not document:
                        logger.warning(f"Document {document_id} not found for embedding update")
                        return

                    # Update document with embedding info
                    stmt = update(FileDocument).where(
                        FileDocument.id == document_id
                    ).values(
                        embedding=embedding,
                        embedding_model=self.embedding_service.get_embedding_model(),
                        embedding_dimensions=self.embedding_service.get_embedding_dimensions(),
                    )

                    await db.execute(stmt)
                    await db.commit()

                    logger.debug(f"Updated embedding info for document {document_id}")

                except Exception as e:
                    await db.rollback()
                    raise e
                finally:
                    await db.close()

        except Exception as e:
            logger.error(f"Failed to update document embedding info for {document_id}: {str(e)}")
            # Don't raise the exception to avoid breaking the entire batch process
            # The embeddings are still generated and stored in the vector store


# Global vector store service instance
_vector_store_service: Optional[VectorStoreService] = None


def get_vector_store_service() -> VectorStoreService:
    """
    Get the global vector store service instance.

    Returns:
        VectorStoreService instance
    """
    global _vector_store_service
    if _vector_store_service is None:
        _vector_store_service = VectorStoreService()
    return _vector_store_service

