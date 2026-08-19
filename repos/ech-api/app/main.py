"""
FastAPI 应用程序入口点，支持扩展机制
可通过工厂函数注入额外路由、中间件、启动/关闭钩子，便于模块化扩展（如SaaS模块）
"""

from typing import Callable, List, Optional, Any
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from pydantic import ValidationError
from fastapi.openapi.utils import get_openapi

# 核心 API 路由
from app.api.v1.router import api_router
# 项目配置
from app.core.config import settings
# 启动日志横幅、权限初始化数据
from app.core.dev_data import log_startup_banner, ensure_permissions_seed
# 自定义异常与全局异常处理器
from app.core.exceptions import (
    TGOAPIException,                  # 项目自定义基础异常
    general_exception_handler,        # 通用异常处理器
    http_exception_handler,           # HTTP 异常处理器
    tgo_api_exception_handler,        # 自定义业务异常处理器
    validation_exception_handler,     # 参数校验异常处理器
)
# 统一错误响应模型
from app.schemas.base import ErrorResponse
# 日志初始化
from app.core.logging import setup_logging
# 平台类型数据初始化
from app.services.platform_type_seed import ensure_platform_types_seed


# ====================== 全局初始化 ======================
# 初始化项目日志系统
setup_logging()

# 调整 uvicorn 内置日志级别，减少启动时冗余日志
import logging
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)


# ====================== FastAPI 应用工厂函数 ======================
def create_app(
    additional_routers: Optional[List[APIRouter]] = None,
    additional_middlewares: Optional[List[tuple[Any, dict]]] = None,
    startup_hooks: Optional[List[Callable]] = None,
    shutdown_hooks: Optional[List[Callable]] = None,
) -> FastAPI:
    """
    创建并配置 FastAPI 应用实例（工厂模式）

    该工厂函数允许扩展模块（如SaaS、插件）注入：
    - 额外路由
    - 额外中间件
    - 自定义启动钩子
    - 自定义关闭钩子

    Args:
        additional_routers: 额外的 APIRouter 列表
        additional_middlewares: 中间件元组列表，格式 (中间件类, 参数字典)
        startup_hooks: 启动时执行的钩子函数列表
        shutdown_hooks: 关闭时执行的钩子函数列表

    Returns:
        完整配置好的 FastAPI 应用实例

    Example:
        from app.main import create_app
        from .routers import billing_router
        app = create_app(additional_routers=[billing_router])
    """
    # 1. 创建 FastAPI 主应用实例
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.PROJECT_VERSION,
        # OpenAPI / Swagger / ReDoc 统一挂载到 /v1 前缀下
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
    )

    # 2. 配置跨域中间件 CORS
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,  # 允许的来源
        allow_credentials=True,                       # 允许携带 Cookie
        allow_methods=["*"],                          # 允许所有请求方法
        allow_headers=["*"],                          # 允许所有请求头
    )

    # 3. 注册外部传入的额外中间件
    if additional_middlewares:
        for middleware_class, kwargs in additional_middlewares:
            application.add_middleware(middleware_class, **kwargs)

    # 4. 注册全局异常处理器（优先级：自定义 > HTTP > 校验 > 通用）
    application.add_exception_handler(TGOAPIException, tgo_api_exception_handler)
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(ValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, general_exception_handler)

    # 5. 挂载核心业务 API 路由（/v1 前缀）
    application.include_router(api_router, prefix=settings.API_V1_STR)

    # 6. 挂载额外扩展路由
    if additional_routers:
        for router in additional_routers:
            application.include_router(router, prefix=settings.API_V1_STR)

    # ====================== 自定义 OpenAPI 文档 ======================
    def custom_openapi() -> dict:
        """
        自定义生成 OpenAPI 规范
        主要目的：统一替换默认的校验错误响应为项目自定义 ErrorResponse
        """
        # 缓存已生成的 schema，避免重复生成
        if application.openapi_schema:
            return application.openapi_schema

        # 生成基础 OpenAPI 结构
        openapi_schema = get_openapi(
            title=settings.PROJECT_NAME,
            version=settings.PROJECT_VERSION,
            description=settings.PROJECT_DESCRIPTION,
            routes=application.routes,
        )

        # 获取/创建 components.schemas 节点
        components = openapi_schema.setdefault("components", {}).setdefault("schemas", {})

        # 将 ErrorResponse 模型加入 OpenAPI 组件
        error_schema = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
        # 提取并注册模型内部定义（$defs）
        defs = error_schema.pop("$defs", {})
        for name, schema in defs.items():
            components[name] = schema
        components["ErrorResponse"] = error_schema

        # 删除 FastAPI 默认生成的校验错误模型，保持文档整洁统一
        components.pop("HTTPValidationError", None)
        components.pop("ValidationError", None)

        # 遍历所有接口，将 422 校验错误统一替换为自定义 ErrorResponse
        for path_item in openapi_schema.get("paths", {}).values():
            for operation in list(path_item.values()):
                if not isinstance(operation, dict):
                    continue
                responses = operation.setdefault("responses", {})

                # 替换原有引用
                for status_code, response in list(responses.items()):
                    content = response.get("content")
                    if not content:
                        continue
                    for content_type, media in list(content.items()):
                        schema = media.get("schema")
                        if not schema:
                            continue
                        ref = schema.get("$ref")
                        if ref and ref.endswith("HTTPValidationError"):
                            media["schema"] = {"$ref": "#/components/schemas/ErrorResponse"}

                # 强制统一 422 响应结构
                if "422" in responses:
                    responses["422"] = {
                        "description": "Validation Error",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                            }
                        },
                    }

        # 缓存并返回最终 OpenAPI 结构
        application.openapi_schema = openapi_schema
        return application.openapi_schema

    # 替换 FastAPI 默认的 openapi 方法
    application.openapi = custom_openapi

    # ====================== 应用启动事件 ======================
    @application.on_event("startup")
    async def startup_event():
        """应用启动时执行的初始化逻辑"""
        from app.core.logging import startup_log

        # 打印启动横幅
        log_startup_banner()

        # 初始化平台类型数据（幂等，重复执行无害）
        try:
            ensure_platform_types_seed()
        except Exception:
            pass  # 尽力而为，不阻塞启动

        # 初始化权限数据（幂等）
        try:
            ensure_permissions_seed()
        except Exception:
            pass

        startup_log("🗄️  Connecting to database...")

        # 启动平台同步监控，主要是为了处理平台同步失败的重试逻辑
        try:
            from app.services.platform_sync import start_sync_monitor
            start_sync_monitor()
        except Exception:
            pass

        # 启动定时任务：同步 AI 服务商配置
        try:
            from app.tasks.sync_ai_providers import start_ai_provider_sync_task
            start_ai_provider_sync_task()
        except Exception:
            pass

        # 启动定时任务：同步项目 AI 配置
        try:
            from app.tasks.sync_project_ai_configs import start_project_ai_config_sync_task
            start_project_ai_config_sync_task()
        except Exception:
            pass

        # 启动定时任务：处理等待队列
        try:
            from app.tasks.process_waiting_queue import start_queue_processor
            start_queue_processor()
        except Exception:
            pass

        # 启动定时任务：关闭超时会话
        try:
            from app.tasks.close_timeout_sessions import start_session_timeout_task
            await start_session_timeout_task()
        except Exception:
            pass

        # 启动定时任务：同步访客在线状态
        try:
            from app.tasks.sync_visitor_online_status import start_visitor_online_sync_task
            await start_visitor_online_sync_task()
        except Exception:
            pass

        # 启动定时任务：自动 AI 兜底切换
        try:
            from app.tasks.auto_fallback_to_ai import start_auto_fallback_to_ai_task
            await start_auto_fallback_to_ai_task()
        except Exception:
            pass

        # 执行外部传入的启动钩子
        if startup_hooks:
            for hook in startup_hooks:
                try:
                    result = hook()
                    # 如果是异步函数，自动 await
                    if hasattr(result, '__await__'):
                        await result
                except Exception:
                    pass

        # 启动完成日志
        startup_log("🌐 Server starting...")
        startup_log(f"   📍 Listening on: http://0.0.0.0:8000")
        startup_log(f"   📚 API Docs: http://localhost:8000/v1/docs")
        startup_log(f"   🏥 Health Check: http://localhost:8000/health")
        startup_log("")
        startup_log("🎉 TGO-Tech API Service is ready!")
        startup_log("═" * 64)

    # ====================== 应用关闭事件 ======================
    @application.on_event("shutdown")
    async def shutdown_event():
        """应用关闭时优雅停止后台任务"""
        # 停止 AI 服务商同步任务
        try:
            from app.tasks.sync_ai_providers import stop_ai_provider_sync_task
            await stop_ai_provider_sync_task()
        except Exception:
            pass

        # 停止项目 AI 配置同步任务
        try:
            from app.tasks.sync_project_ai_configs import stop_project_ai_config_sync_task
            await stop_project_ai_config_sync_task()
        except Exception:
            pass

        # 停止等待队列处理器
        try:
            from app.tasks.process_waiting_queue import stop_queue_processor
            await stop_queue_processor()
        except Exception:
            pass

        # 停止会话超时检查任务
        try:
            from app.tasks.close_timeout_sessions import stop_session_timeout_task
            await stop_session_timeout_task()
        except Exception:
            pass

        # 停止访客在线状态同步
        try:
            from app.tasks.sync_visitor_online_status import stop_visitor_online_sync_task
            await stop_visitor_online_sync_task()
        except Exception:
            pass

        # 停止自动 AI 兜底任务
        try:
            from app.tasks.auto_fallback_to_ai import stop_auto_fallback_to_ai_task
            await stop_auto_fallback_to_ai_task()
        except Exception:
            pass

        # 执行外部关闭钩子
        if shutdown_hooks:
            for hook in shutdown_hooks:
                try:
                    result = hook()
                    if hasattr(result, '__await__'):
                        await result
                except Exception:
                    pass

    # ====================== 根路由与健康检查 ======================
    @application.get("/")
    async def root() -> dict[str, str]:
        """根接口：服务信息"""
        return {"message": "TGO-Tech API Service", "version": settings.PROJECT_VERSION}

    @application.get("/health")
    async def health_check() -> dict[str, str]:
        """健康检查接口：用于容器/负载均衡探测"""
        return {"status": "healthy"}

    # 返回配置完成的应用
    return application


# ====================== 默认创建应用实例 ======================
# 兼容直接运行：uvicorn app.main:app
app = create_app()


# ====================== 直接运行入口 ======================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,       # 开发模式热重载
        log_level="info",
    )
'''核心结构总结（便于快速理解）
工厂模式 create_app()
高度可扩展，支持外部注入路由、中间件、启动 / 关闭钩子，适合微服务 / 插件化架构。
全局异常统一处理
自定义异常 + 统一错误响应模型，接口返回格式高度规范。
OpenAPI 定制
去掉 FastAPI 默认的 HTTPValidationError，全部替换为项目统一 ErrorResponse，文档更专业。
启动 / 关闭生命周期管理
批量启动 / 停止各类定时任务、后台同步、队列处理器，且全部尽力而为（best-effort），不阻塞主服务启动。
健康检查 + 根接口
适配 K8s / Docker 部署。'''