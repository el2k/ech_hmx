#!/usr/bin/env python3
"""
Initialize the RAG service project with sample data.
"""

import asyncio
import logging
import sys
from pathlib import Path
from uuid import uuid4

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rag_service.config import get_settings
from rag_service.database import get_db_session, init_database
from rag_service.models import Collection, Project

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 创建一个异步函数来创建一个示例项目
async def create_sample_project():
    """Create a sample project for testing."""
    async with get_db_session() as db:
        # Create sample project
        project = Project(
            id=uuid4(),
            name="Sample Project",
            api_key="sample-api-key-12345",
        )
        
        db.add(project)
        await db.commit()
        await db.refresh(project)
        
        logger.info(f"Created sample project: {project.id}")
        return project

# 创建一个异步函数来创建一个示例集合
async def create_sample_collection(project: Project):
    """Create a sample collection for testing."""
    async with get_db_session() as db:
        # Create sample collection
        collection = Collection(
            project_id=project.id,
            display_name="Sample Collection",
            description="A sample collection for testing the RAG service",
            collection_metadata={
                "embedding_model": "text-embedding-ada-002",
                "chunk_size": 1000,
                "chunk_overlap": 200,
                "language": "en"
            }
        )
        
        db.add(collection)
        await db.commit()
        await db.refresh(collection)
        
        logger.info(f"Created sample collection: {collection.id}")
        return collection


async def main():
    """Main initialization function."""
    logger.info("Initializing RAG service project...")
    
    # Initialize database
    logger.info("Initializing database...")
    await init_database()
    
    # Create sample data
    logger.info("Creating sample data...")
    project = await create_sample_project()
    collection = await create_sample_collection(project)
    
    logger.info("Project initialization completed!")
    logger.info(f"Sample project ID: {project.id}")
    logger.info(f"Sample collection ID: {collection.id}")
    logger.info(f"API key: {project.api_key}")


if __name__ == "__main__":
    asyncio.run(main())
