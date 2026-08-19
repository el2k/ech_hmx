"""Base Pydantic schemas for common structures."""

import uuid
from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base schema with common configuration."""

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        str_strip_whitespace=True,
    )


class TimestampMixin(BaseSchema):
    """Mixin for timestamp fields."""

    created_at: datetime = Field(description="Record creation timestamp")
    updated_at: datetime = Field(description="Record last update timestamp")
    deleted_at: Optional[datetime] = Field(
        default=None, description="Soft delete timestamp"
    )


class PaginationMetadata(BaseSchema):
    """Pagination metadata for list responses."""

    total: int = Field(description="Total number of items", ge=0)
    limit: int = Field(description="Number of items per page", ge=1, le=100)
    offset: int = Field(description="Number of items skipped", ge=0)
    has_next: bool = Field(description="Whether there are more items")
    has_prev: bool = Field(description="Whether there are previous items")


class IDMixin(BaseSchema):
    """Mixin for ID field."""

    id: uuid.UUID = Field(description="Unique identifier")


# Generic type for paginated responses
T = TypeVar('T')


class PaginatedResponse(BaseSchema, Generic[T]):
    """Generic paginated response model."""

    data: List[T] = Field(description="List of items")
    pagination: PaginationMetadata = Field(description="Pagination metadata")
