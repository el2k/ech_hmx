"""
Pydantic schemas for project-level embedding configuration.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EmbeddingConfigCreate(BaseModel):
    """Schema for creating/upserting an embedding configuration entry."""

    project_id: UUID = Field(..., description="Upstream project ID (not validated against rag_projects)")
    provider: str = Field(..., description="Embedding provider (any string, stored as-is)")
    model: str = Field(..., description="Embedding model name")
    dimensions: int = Field(1536, description="Embedding dimensions; must be 1536 in phase 1")
    batch_size: int = Field(10, description="Batch size for embedding generation")
    api_key: Optional[str] = Field(None, description="Provider API key (stored as plain text)")
    base_url: Optional[str] = Field(None, description="Provider base URL (for Qwen3 or custom endpoints)")
    is_active: bool = Field(True, description="Whether this config is active; batch sync targets active config")


class EmbeddingConfigBatchSyncRequest(BaseModel):
    """Request body for batch syncing embedding configurations."""

    configs: List[EmbeddingConfigCreate] = Field(..., description="List of configurations to upsert")


class EmbeddingConfigBatchSyncResponse(BaseModel):
    """Response for batch sync indicating successes and failures."""

    success_count: int = Field(..., description="Number of successfully processed configurations")
    failed_count: int = Field(..., description="Number of configurations that failed to process")
    errors: List[dict] = Field(default_factory=list, description="List of error details per failed item")


class EmbeddingConfigResponse(BaseModel):
    """Schema for returning an embedding configuration (excluding API key for safety)."""

    id: UUID
    project_id: UUID
    provider: str
    model: str
    dimensions: int
    batch_size: int
    base_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

