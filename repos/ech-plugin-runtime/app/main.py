"""FastAPI application entry point for TGO Plugin Runtime."""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.logging import setup_logging, startup_log

# Setup logging
setup_logging()
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Application lifespan manager."""
    # Startup logic
    from app.services.socket_server import start_socket_server
    from app.services.tool_sync import setup_tool_sync
    from app.services.process_manager import process_manager
    from app.core.database import SessionLocal
    import app.models  # Ensure models are loaded
    from app.models.plugin import InstalledPlugin

    startup_log("=" * 64)
    startup_log("🔌 TGO Plugin Runtime Service Starting...")
    startup_log("=" * 64)

    # Setup tool sync with plugin manager
    # 建立与插件管理器的工具同步
    setup_tool_sync()

    # Start socket server FIRST so plugins can connect on startup
    # 开启 socket 服务器，以便插件在启动时可以连接
    await start_socket_server()

    # Start process manager monitor
    # 启动进程管理器监控
    await process_manager.start()

    # Auto-start installed plugins
    try:
        with SessionLocal() as db:
            # 这里查询数据库中所有状态为 "running" 或 "starting" 的已安装插件，并尝试自动启动它们。
            installed_plugins = db.query(InstalledPlugin).filter(
                InstalledPlugin.status.in_(["running", "starting"])
            ).all()
            
            if installed_plugins:
                startup_log(f"🚀 Auto-starting {len(installed_plugins)} plugins...")
                for p in installed_plugins:
                    config = {
                        "id": p.plugin_id,
                        "name": p.name,
                        "version": p.version,
                        "source": p.source_config,
                        "build": p.build_config,
                        "runtime": p.runtime_config
                    }
                    asyncio.create_task(process_manager.start_plugin(p.plugin_id, config))
    except Exception as e:
        startup_log(f"❌ Failed to auto-start plugins: {e}")

    startup_log(f"   📍 HTTP API: http://0.0.0.0:{settings.PORT}")
    startup_log(f"   📚 API Docs: http://localhost:{settings.PORT}/docs")
    startup_log(f"   🏥 Health Check: http://localhost:{settings.PORT}/health")
    startup_log("")
    startup_log("🎉 Plugin Runtime Service is ready!")
    startup_log("=" * 64)

    yield

    # Shutdown logic
    from app.services.socket_server import stop_socket_server
    from app.services.plugin_manager import plugin_manager
    from app.services.process_manager import process_manager
    # 先关闭所有插件，再停止进程管理器，最后关闭 socket 服务器，以确保资源的正确释放和服务的平稳关闭。
    await plugin_manager.shutdown_all()
    await process_manager.stop()
    await stop_socket_server()


app = FastAPI(
    title=settings.SERVICE_NAME,
    description="Plugin Runtime Service for TGO - manages plugin connections and provides HTTP APIs",
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# Include API routes
from app.api.routes import router as api_router

app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.is_development,
    )

