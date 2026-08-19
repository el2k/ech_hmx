"""Custom exception classes for the application."""

import uuid
from typing import Any, Dict, Optional

# TGOAIServiceException 是一个自定义的异常类，用于表示 TGO AI 服务中的各种错误情况。它继承自 Python 的内置 Exception 类，并添加了额外的属性来提供更多的错误信息。
class TGOAIServiceException(Exception):
    """Base exception for TGO AI Service."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(self.message)

# AuthenticationError 是 TGOAIServiceException 的一个子类，表示身份验证失败的错误。它在初始化时设置了默认的错误消息和错误代码。
class AuthenticationError(TGOAIServiceException):
    """Authentication failed."""

    def __init__(
        self,
        message: str = "Authentication failed",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, "AUTHENTICATION_FAILED", details)
# AuthorizationError 是 TGOAIServiceException 的另一个子类，表示授权失败的错误。它在初始化时设置了默认的错误消息和错误代码。
class AuthorizationError(TGOAIServiceException):
    """Authorization failed."""

    def __init__(
        self,
        message: str = "Access denied",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, "ACCESS_DENIED", details)
# NotFoundError 是 TGOAIServiceException 的一个子类，表示资源未找到的错误。它在初始化时接受资源类型和可选的资源 ID，并构建一个详细的错误消息和错误代码。
class NotFoundError(TGOAIServiceException):
    """Resource not found."""

    def __init__(
        self,
        resource: str,
        resource_id: Optional[uuid.UUID] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        message = f"{resource} not found"
        if resource_id:
            message += f" (ID: {resource_id})"
        
        error_details = details or {}
        if resource_id:
            error_details["resource_id"] = str(resource_id)
        error_details["resource_type"] = resource
        
        super().__init__(message, f"{resource.upper()}_NOT_FOUND", error_details)
# ValidationError 是 TGOAIServiceException 的一个子类，表示数据验证失败的错误。它在初始化时接受一个可选的字段名称，并将其包含在错误详情中。
class ValidationError(TGOAIServiceException):
    """Data validation failed."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        error_details = details or {}
        if field:
            error_details["field"] = field
        
        super().__init__(message, "VALIDATION_ERROR", error_details)
# ConflictError 是 TGOAIServiceException 的一个子类，表示资源冲突的错误。它在初始化时接受一个可选的资源类型，并将其包含在错误详情中，同时根据资源类型生成相应的错误代码。
class ConflictError(TGOAIServiceException):
    """Resource conflict."""

    def __init__(
        self,
        message: str,
        resource: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        error_details = details or {}
        if resource:
            error_details["resource_type"] = resource
        
        code = f"{resource.upper()}_CONFLICT" if resource else "CONFLICT"
        super().__init__(message, code, error_details)
# DatabaseError 是 TGOAIServiceException 的一个子类，表示数据库操作失败的错误。它在初始化时设置了默认的错误消息和错误代码。
class DatabaseError(TGOAIServiceException):
    """Database operation failed."""

    def __init__(
        self,
        message: str = "Database operation failed",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, "DATABASE_ERROR", details)
# ExternalServiceError 是 TGOAIServiceException 的一个子类，表示外部服务调用失败的错误。它在初始化时接受一个服务名称，并将其包含在错误详情中，同时设置默认的错误消息和错误代码。
class ExternalServiceError(TGOAIServiceException):
    """External service call failed."""

    def __init__(
        self,
        service: str,
        message: str = "External service call failed",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        error_details = details or {}
        error_details["service"] = service
        
        super().__init__(message, "EXTERNAL_SERVICE_ERROR", error_details)

# RateLimitError 是 TGOAIServiceException 的一个子类，表示请求速率限制被超过的错误。它在初始化时设置了默认的错误消息和错误代码。
class RateLimitError(TGOAIServiceException):
    """Rate limit exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, "RATE_LIMIT_EXCEEDED", details)

