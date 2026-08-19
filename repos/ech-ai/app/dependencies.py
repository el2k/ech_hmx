"""FastAPI dependencies for authentication and database access."""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator, Optional
from functools import lru_cache

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key import get_project_from_api_key
from app.auth.jwt import get_project_from_jwt
from app.config import settings
from app.database import AsyncSessionLocal, get_db
from app.exceptions import AuthenticationError
from app.models.project import Project
from app.runtime.supervisor.application.service import SupervisorRuntimeService
from app.runtime.tools.executor.service import ToolsRuntimeService
from app.services.agent_service import AgentService
from app.services.llm_provider_service import LLMProviderService

# Security scheme for JWT tokens
security = HTTPBearer(auto_error=False)
@asynccontextmanager
async def _get_session_from_app(request: Request) -> AsyncIterator[AsyncSession]:
    """Acquire a DB session respecting dependency overrides on the FastAPI app.
    # 从FastAPI app获取数据库会话的异步上下文管理器
    # 核心作用：兼容app.dependency_overrides，单元测试/集成测试时可以替换get_db依赖；不走直接导入get_db，而是读取app上的依赖覆盖
    # get_db是原始获取db会话的依赖函数，测试环境会被dependency_overrides替换成mock会话
    """
    # 取出被覆盖后的db依赖，如果没有被覆盖，就使用原生get_db
    dependency = request.app.dependency_overrides.get(get_db, get_db)
    # 调用依赖，得到异步生成器（get_db是async yield生成器）
    generator = dependency()
    try:
        # 执行 __anext__ 拿到生成器产出的AsyncSession数据库会话
        session = await generator.__anext__()
    except StopAsyncIteration as exc:  # pragma: no cover - defensive
        # 防御性捕获：生成器没有yield出session直接结束，属于异常场景
        raise RuntimeError("Database dependency did not yield a session") from exc
    try:
        yield session  # type: ignore[generator-type]
        # 向外产出db会话，给上层业务使用
    finally:
        # 无论是否发生异常，必须关闭异步生成器，触发get_db内部的会话释放/回收逻辑
        await generator.aclose()


async def get_current_project(
    request: Request,
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Project:
    """
    Get the current project from either JWT token or API key.
    # FastAPI依赖：认证并解析出当前请求所属Project项目对象
    # 支持两套认证方式，优先JWT Bearer Token，降级X‑API‑Key；二选一
    Supports two authentication methods:
    1. JWT token in Authorization header: Bearer <token>
    2. API key in X-API-Key header

    Args:
        request: FastAPI request 对象
        authorization: JWT解析出来的凭证对象，由security这个Depends解析Authorization: Bearer xxx头部

    Returns:
        Authenticated project 认证通过返回Project ORM实例

    Raises:
        HTTPException / AuthenticationError: 认证失败抛出认证异常
    """
    # 方案1：优先走JWT Bearer认证
    if authorization and authorization.credentials:
        # 使用上面封装的上下文管理器拿db会话，兼容测试环境的dependency_overrides
        async with _get_session_from_app(request) as session:
            # 解析JWT，查询数据库得到Project
            return await get_project_from_jwt(authorization.credentials, session)

    # 方案2：JWT不存在，尝试API‑Key认证，读取请求头 X‑API‑Key
    x_api_key = request.headers.get("X-API-Key")
    if x_api_key:
        async with _get_session_from_app(request) as session:
            # 根据api_key查询数据库，返回Project
            return await get_project_from_api_key(x_api_key, session)

    # 两种认证都没有提供，抛出认证错误
    raise AuthenticationError("No authentication provided")


async def get_current_project_id(
    project: Project = Depends(get_current_project),
) -> uuid.UUID:
    """
    Get the current project ID.
    # FastAPI依赖：直接拿到当前认证后的project_id，接口不需要拿到完整Project对象时使用
    
    Args:
        project: 由get_current_project依赖注入已经认证完成的Project实例
        
    Returns:
        Project UUID 项目唯一ID
    """
    return project.id


def get_pagination_params(
    limit: int = Query(default=20, ge=1, le=100, description="Number of items to return"),
    offset: int = Query(default=0, ge=0, description="Number of items to skip"),
) -> tuple[int, int]:
    """
    Get pagination parameters with validation.
    # FastAPI依赖：统一解析分页参数，自带参数校验
    limit范围1‑100，offset≥0；返回(limit, offset)元组直接给SQLAlchemy查询使用

    Args:
        limit: Number of items to return (1‑100)
        offset: Number of items to skip (>=0)

    Returns:
        Tuple of (limit, offset)
    """
    return limit, offset


def get_agent_service(db: AsyncSession = Depends(get_db)) -> AgentService:
    """
    Get AgentService instance.
    # FastAPI依赖注入AgentService业务服务实例
    # 每次请求拿到独立db会话，实例化AgentService，路由中 Depends(get_agent_service)即可直接拿到service对象

    Args:
        db: Database session 由get_db依赖注入异步会话

    Returns:
        AgentService instance
    """
    return AgentService(db)


def get_llm_provider_service(db: AsyncSession = Depends(get_db)) -> LLMProviderService:
    """Get LLMProviderService instance.
    # FastAPI依赖注入LLMProviderService，每次请求新建服务实例，绑定本次请求的db会话
    """
    return LLMProviderService(db)


@lru_cache
def get_tools_runtime_service() -> ToolsRuntimeService:
    """获取工具智能体运行时服务实例 (singleton).
    # lru_cache装饰器：单例，全局只初始化一次，所有请求复用同一个ToolsRuntimeService对象
    # 无数据库会话，是运行时服务，不绑定单次http请求生命周期，读取全局settings配置
    """
    return ToolsRuntimeService(runtime_settings=settings.tools_runtime)


@lru_cache
def get_supervisor_runtime_service() -> SupervisorRuntimeService:
    """获取Supervisor运行时服务实例 (singleton).
    # 全局单例SupervisorRuntimeService，lru_cache保证只实例化一次
    # 注入数据库会话工厂AsyncSessionLocal（不是单次请求session，是工厂，内部自己生成会话）
    # 依赖已经单例的tools_runtime_service
    """
    return SupervisorRuntimeService(
        session_factory=AsyncSessionLocal,
        tools_runtime_service=get_tools_runtime_service(),
    )