"""
Authentication models and schemas for API key-based authentication.
"""

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectAccess(BaseModel):
    """Project access information from API key authentication."""

    project_id: UUID = Field(..., description="Project unique identifier")
    api_key: str = Field(..., description="Project API key")
    name: str = Field(..., description="Project name")
    is_active: bool = Field(True, description="Whether project is active")


class ApiKeyValidationResult(BaseModel):
    """Result of API key validation."""

    is_valid: bool = Field(..., description="Whether the API key is valid")
    project: Optional[ProjectAccess] = Field(None, description="Project information if valid")
    error: Optional[str] = Field(None, description="Error message if invalid")
