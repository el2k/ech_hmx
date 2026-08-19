"""
Pytest configuration and fixtures for RAG service tests.
"""

import asyncio
import os
import tempfile
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer

from src.rag_service.config import Settings, get_settings
from src.rag_service.database import get_db_session_dependency
from src.rag_service.main import create_app
from src.rag_service.models import Base


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Start a PostgreSQL container for testing."""
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        # Wait for the container to be ready
        postgres.get_connection_url()
        yield postgres


@pytest.fixture(scope="session")
def test_settings(postgres_container: PostgresContainer) -> Settings:
    """Create test settings with test database URL."""
    # Create temporary upload directory
    temp_dir = tempfile.mkdtemp()
    
    # Get the connection URL and ensure it uses asyncpg
    connection_url = postgres_container.get_connection_url()
    # Replace any postgresql driver with asyncpg for async support
    if "postgresql+psycopg2://" in connection_url:
        async_connection_url = connection_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    elif connection_url.startswith("postgresql://"):
        async_connection_url = connection_url.replace("postgresql://", "postgresql+asyncpg://")
    else:
        async_connection_url = connection_url

    # Override settings for testing
    test_env = {
        "DATABASE_URL": async_connection_url,
        "REDIS_URL": "redis://localhost:6379/1",  # Use different DB for tests
        "UPLOAD_DIR": temp_dir,
        "ENVIRONMENT": "test",
        "DEBUG": "true",
        "LOG_LEVEL": "debug",
        "JWT_SECRET_KEY": "test-secret-key",
        "OPENAI_API_KEY": "test-openai-key",
        "METRICS_ENABLED": "false",
    }
    
    # Set environment variables
    for key, value in test_env.items():
        os.environ[key] = value
    
    # Create settings instance
    settings = Settings()
    
    yield settings
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    
    # Restore original environment
    for key in test_env:
        os.environ.pop(key, None)


@pytest_asyncio.fixture(scope="session")
async def test_engine(test_settings: Settings):
    """Create test database engine."""
    engine = create_async_engine(
        test_settings.database_url,
        echo=test_settings.debug,
        pool_pre_ping=True,
    )
    
    # Create all tables
    async with engine.begin() as conn:
        # Enable pgvector extension first
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    
    yield engine
    
    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with async_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def override_get_settings(test_settings: Settings):
    """Override the get_settings dependency."""
    def _get_test_settings():
        return test_settings
    return _get_test_settings


@pytest.fixture
def override_get_db(db_session: AsyncSession):
    """Override the database dependency."""
    async def _get_test_db():
        yield db_session
    return _get_test_db


@pytest.fixture
def test_app(override_get_settings, override_get_db):
    """Create test FastAPI application with overridden dependencies."""
    app = create_app()
    
    # Override dependencies
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_db_session_dependency] = override_get_db
    
    yield app
    
    # Clear overrides
    app.dependency_overrides.clear()


@pytest.fixture
def test_client(test_app) -> TestClient:
    """Create test client for the FastAPI application."""
    return TestClient(test_app)


# Test data factories
@pytest.fixture
def sample_collection_data():
    """Sample collection data for testing."""
    return {
        "display_name": "Test Collection",
        "description": "A test collection for unit tests",
        "collection_metadata": {
            "embedding_model": "text-embedding-ada-002",
            "chunk_size": 1000,
            "chunk_overlap": 200,
        }
    }


@pytest.fixture
def sample_file_data():
    """Sample file data for testing."""
    return {
        "original_filename": "test_document.pdf",
        "file_size": 1024,
        "content_type": "application/pdf",
        "storage_provider": "local",
        "storage_path": "/tmp/test_document.pdf",
        "status": "pending",
        "language": "en",
        "description": "Test document for unit tests",
    }


@pytest.fixture
def sample_document_data():
    """Sample document data for testing."""
    return {
        "document_id": "test_doc_001",
        "document_title": "Test Document",
        "content": "This is a test document content for RAG processing.",
        "content_length": 50,
        "content_type": "paragraph",
        "language": "en",
        "chunk_index": 0,
        "confidence_score": 0.95,
    }
