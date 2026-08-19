"""
Common Pydantic schemas used across the application.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field
# 这段代码定义了 ErrorResponse，它是整个 API 的全局标准错误响应模型。
# 在优秀的后端架构中，成功和失败的返回格式都应该是高度结构化且一致的。
# 这个模型确保了无论发生什么错误，前端或调用方都能拿到格式统一、易于解析的错误信息，而不是乱七八糟的纯文本或原生异常堆栈。
class ErrorResponse(BaseModel):
    error: Dict[str, Any] = Field(
        ...,
        description="Error details",
        examples=[
            {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request data",
                "details": {"field": "name", "issue": "Field is required"}
            }
        ]
    )
# PaginationParams 是一个用于分页请求的 Pydantic 模型，包含了分页相关的参数字段，如限制和偏移量。
class PaginationParams(BaseModel):
    """Pagination parameters for list endpoints."""
    
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of items to return"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of items to skip"
    )

# paginationMetadata 是一个用于分页响应的 Pydantic 模型，包含了分页相关的元数据字段，如总数、限制、偏移量以及是否有下一页和上一页的标志。
class PaginationMetadata(BaseModel):
    """Pagination metadata for list responses."""
    
    total: int = Field(
        ...,
        ge=0,
        description="Total number of items available"
    )
    limit: int = Field(
        ...,
        ge=1,
        description="Number of items requested"
    )
    offset: int = Field(
        ...,
        ge=0,
        description="Number of items skipped"
    )
    has_next: bool = Field(
        ...,
        description="Whether there are more items available"
    )
    has_prev: bool = Field(
        ...,
        description="Whether there are previous items available"
    )

# HealthResponse 是一个用于健康检查响应的 Pydantic 模型，包含了应用程序的整体健康状态、版本、时间戳以及各个组件的健康检查结果。
class HealthResponse(BaseModel):
    """Health check response schema."""
    
    status: str = Field(
        ...,
        description="Overall health status",
        examples=["healthy", "unhealthy", "degraded"]
    )
    version: str = Field(
        ...,
        description="Application version"
    )
    timestamp: str = Field(
        ...,
        description="Health check timestamp (ISO format)"
    )
    checks: Dict[str, Any] = Field(
        ...,
        description="Individual health check results",
        examples=[
            {
                "database": {"status": "healthy", "response_time_ms": 15},
                "redis": {"status": "healthy", "response_time_ms": 5},
                "vector_db": {"status": "healthy", "response_time_ms": 25}
            }
        ]
    )
# MetricsResponse 是一个用于指标响应的 Pydantic 模型，包含了应用程序的各种指标数据以及时间戳。
class MetricsResponse(BaseModel):
    """Metrics response schema."""
    
    metrics: Dict[str, Any] = Field(
        ...,
        description="Application metrics",
        examples=[
            {
                "requests_total": 1234,
                "requests_per_second": 12.5,
                "response_time_p95": 150.0,
                "active_connections": 25,
                "documents_processed": 5678,
                "embeddings_generated": 9012
            }
        ]
    )
    timestamp: str = Field(
        ...,
        description="Metrics collection timestamp (ISO format)"
    )
# StatusResponse 是一个通用的状态响应 Pydantic 模型，包含了操作状态、可选的状态消息以及可选的附加状态详情。
class StatusResponse(BaseModel):
    """Generic status response schema."""
    
    status: str = Field(
        ...,
        description="Operation status",
        examples=["success", "pending", "failed"]
    )
    message: Optional[str] = Field(
        None,
        description="Status message"
    )
    details: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional status details"
    )