"""
Authentication dependencies for API key-based multi-tenant access.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db_session_dependency
from ..logging_config import get_logger
from ..models.projects import Project
from .models import ApiKeyValidationResult, ProjectAccess
from .security import SecurityAuditLogger

logger = get_logger(__name__)

# Define the API key security scheme for OpenAPI documentation
api_key_header = APIKeyHeader(
    name="X-API-Key",
    description="API key for project authentication. Each project has a unique API key that provides access to project-scoped resources."
)

# 获得api_key_header的依赖项
async def get_api_key_from_header(
    api_key: str = Depends(api_key_header)
) -> str:
    """
    Extract API key from request header using FastAPI security scheme.

    Args:
        api_key: API key from X-API-Key header (automatically extracted by FastAPI)

    Returns:
        API key string

    Raises:
        HTTPException: If API key is missing (handled automatically by FastAPI)
    """
    if not api_key:
        logger.warning("API key missing from request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Please provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


async def validate_api_key(
    api_key: str,
    db: AsyncSession,
    request: Optional[Request] = None
) -> ApiKeyValidationResult:
    """
    Validate API key against the projects table with security logging.

    Args:
        api_key: API key to validate
        db: Database session
        request: FastAPI request object for audit logging

    Returns:
        ApiKeyValidationResult with validation status and project info
    """
    api_key_prefix = api_key[:8] if len(api_key) >= 8 else api_key
    ip_address = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    try:
        # Query project by API key
        query = select(Project).where(
            Project.api_key == api_key,
            Project.deleted_at.is_(None)
        )

        result = await db.execute(query)
        project = result.scalar_one_or_none()

        if not project:
            # Log security violation
            SecurityAuditLogger.log_api_key_validation(
                api_key_prefix=api_key_prefix,
                project_id=None,
                success=False,
                ip_address=ip_address,
                user_agent=user_agent
            )
            SecurityAuditLogger.log_security_violation(
                violation_type="invalid_api_key",
                details=f"Invalid API key attempted: {api_key_prefix}...",
                api_key_prefix=api_key_prefix,
                ip_address=ip_address
            )

            return ApiKeyValidationResult(
                is_valid=False,
                error="Invalid API key"
            )

        # Create project access info
        # 创建项目访问信息
        project_access = ProjectAccess(
            project_id=project.id,
            api_key=project.api_key,
            name=project.name,
            is_active=True
        )

        # Log successful validation
        SecurityAuditLogger.log_api_key_validation(
            api_key_prefix=api_key_prefix,
            project_id=project.id,
            success=True,
            ip_address=ip_address,
            user_agent=user_agent
        )

        return ApiKeyValidationResult(
            is_valid=True,
            project=project_access
        )

    except Exception as e:
        logger.error("Error validating API key", error=str(e), api_key_prefix=api_key_prefix)
        SecurityAuditLogger.log_security_violation(
            violation_type="api_key_validation_error",
            details=f"API key validation failed: {str(e)}",
            api_key_prefix=api_key_prefix,
            ip_address=ip_address
        )

        return ApiKeyValidationResult(
            is_valid=False,
            error="API key validation failed"
        )


async def get_current_project(
    request: Request,
    api_key: str = Depends(get_api_key_from_header),
    db: AsyncSession = Depends(get_db_session_dependency)
) -> ProjectAccess:
    """
    得到当前项目从API密钥认证与安全日志记录。
    这个依赖项验证API密钥并返回相关的项目。
    所有经过身份验证的端点都应该使用这个依赖项，以确保适当的多租户数据隔离。
    参数:
        request: FastAPI请求对象用于审计日志记录
        api_key: 来自请求头的API密钥
        db: 数据库会话
    返回:
        ProjectAccess包含项目信息
    异常:
        HTTPException: 如果API密钥无效或项目未找到
    """
    validation_result = await validate_api_key(api_key, db, request)

    if not validation_result.is_valid:
        logger.warning("Authentication failed", error=validation_result.error)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=validation_result.error or "Authentication failed",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return validation_result.project

# 请求api_key_header的依赖项
async def require_api_key(
    project: ProjectAccess = Depends(get_current_project)
) -> ProjectAccess:
    """
    Require valid API key authentication.
    
    This is an alias for get_current_project that makes the intent clearer
    when used in endpoints that require authentication.
    
    Args:
        project: Project from get_current_project dependency
        
    Returns:
        ProjectAccess with project information
    """
    return project

# 得到项目ID
def get_project_id(
    project: ProjectAccess = Depends(get_current_project)
) -> UUID:
    """
    Extract project ID from authenticated project.
    
    This dependency provides just the project ID for use in database queries
    and other operations that need project-scoped access.
    
    Args:
        project: Project from get_current_project dependency
        
    Returns:
        Project UUID
    """
    return project.project_id
