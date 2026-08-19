"""Base Pydantic schemas."""
# 项目基础公共Pydantic模型定义
# 包含：基础Schema配置、Mixin混入类、分页模型、统一成功/错误返回体、健康检查、批量操作、搜索参数
# 所有业务Schema应当继承 BaseSchema，复用全局配置

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base schema with common configuration.
    项目所有Pydantic模型的基类，统一全局模型行为配置
    """

    model_config = ConfigDict(
        from_attributes=True,          # 【ORM模式】支持直接从SQLAlchemy ORM对象构建schema，orm_mode别名
        validate_assignment=True,      # 赋值时也做校验：obj.field = xxx 也触发pydantic校验
        arbitrary_types_allowed=True,  # 允许非Pydantic原生类型，适配SQLAlchemy模型、UUID等
        str_strip_whitespace=True,     # 自动对字符串前后去除空格，避免前端传入多余空格
        populate_by_name=True,         # 同时支持别名(alias)和原字段名解析入参
        extra="ignore",                 # 忽略未知额外字段，向前兼容上游服务新增字段，不会报422
    )


class TimestampMixin(BaseModel):
    """Mixin for timestamp fields.
    时间戳混入类；创建、更新时间，数据库模型通用字段，业务schema直接继承复用
    """

    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class SoftDeleteMixin(BaseModel):
    """Mixin for soft delete functionality.
    软删除混入；deleted_at为None代表未删除；有时间代表已逻辑删除
    """

    deleted_at: Optional[datetime] = Field(None, description="Soft deletion timestamp")


class PaginationParams(BaseModel):
    """Pagination parameters.
    请求分页查询参数，用于FastAPI接口入参解析
    limit：单页条数；offset：跳过多少条（offset‑limit分页，非游标分页）
    """

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


class PaginationMetadata(BaseModel):
    """Pagination metadata for responses.
    返回给前端的分页元数据；计算总条数、是否上一页/下一页
    """

    total: int = Field(..., description="Total number of items")
    limit: int = Field(..., description="Number of items per page")
    offset: int = Field(..., description="Number of items skipped")
    has_next: bool = Field(..., description="Whether there are more items")
    has_prev: bool = Field(..., description="Whether there are previous items")


class PaginatedResponse(BaseModel):
    """Generic paginated response.
    通用分页返回包装体；所有列表分页接口统一返回此结构
    """

    data: List[Any] = Field(..., description="List of items")
    pagination: PaginationMetadata = Field(..., description="Pagination metadata")


class ErrorDetail(BaseModel):
    """Error detail schema.
    错误详情内部结构，和前面异常处理器配套
    """

    code: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")


class ErrorResponse(BaseModel):
    """Error response schema.
    API全局统一错误返回外层结构；异常handler输出就是这个模型
    """

    error: ErrorDetail = Field(..., description="Error information")
    request_id: Optional[str] = Field(None, description="Request ID for tracking")


class SuccessResponse(BaseModel):
    """Generic success response.
    通用成功返回包装，简单操作接口可直接使用，不需要单独写schema
    """

    message: str = Field(..., description="Success message")
    data: Optional[Any] = Field(None, description="Response data")


class HealthCheckResponse(BaseModel):
    """Health check response schema.
    /health健康检查接口返回体；监控系统探测使用，包含数据库连通性、版本
    """

    status: str = Field(..., description="Health status")
    timestamp: datetime = Field(..., description="Check timestamp")
    version: str = Field(..., description="Application version")
    database: bool = Field(..., description="Database connectivity status")


class BulkOperationResponse(BaseModel):
    """Bulk operation response schema.
    批量操作返回模型：批量新增/删除/导入，统计成功失败数量，携带每条失败详情
    """

    total: int = Field(..., description="Total number of items processed")
    successful: int = Field(..., description="Number of successful operations")
    failed: int = Field(..., description="Number of failed operations")
    errors: List[ErrorDetail] = Field(default_factory=list, description="List of errors")


class SearchParams(BaseModel):
    """Search parameters.
    通用搜索查询参数；支持关键词搜索、排序字段、升降序
    sort_order 使用正则约束只允许 asc / desc
    """

    search: Optional[str] = Field(
        None,
        min_length=1,
        max_length=255,
        description="Search query string"
    )
    sort_by: Optional[str] = Field(
        None,
        description="Field to sort by"
    )
    sort_order: Optional[str] = Field(
        default="asc",
        pattern="^(asc|desc)$",
        description="Sort order: asc or desc"
    )