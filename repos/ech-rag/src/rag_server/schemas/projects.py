"""
Project-related Pydantic schemas.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

# 项目相关的 Pydantic 模式（schemas）定义了用于项目 API 响应的数据结构。它们确保了数据的一致性和验证，便于在应用程序中进行数据传输和处理。
class ProjectResponse(BaseModel):
    """Schema for project API responses."""
    
    id: UUID = Field(
        ...,
        description="Project unique identifier"
    )
    name: str = Field(
        ...,
        description="Project name"
    )
    api_key: str = Field(
        ...,
        description="API key for project authentication"
    )
    created_at: datetime = Field(
        ...,
        description="Project creation timestamp"
    )
    updated_at: datetime = Field(
        ...,
        description="Project last update timestamp"
    )
    deleted_at: Optional[datetime] = Field(
        None,
        description="Project deletion timestamp (if soft deleted)"
    )

    class Config:
        from_attributes = True
