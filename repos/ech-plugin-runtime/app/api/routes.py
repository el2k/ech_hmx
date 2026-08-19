"""Plugin API endpoints."""

import json
import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.logging import get_logger
from app.services.plugin_manager import plugin_manager
from app.services.installer import installer
from app.services.process_manager import process_manager
from app.schemas.plugin import (
    VisitorInfo,
    PluginListResponse,
    PluginInfo,
    PluginRenderRequest,
    PluginEventRequest,
    VisitorPanelRenderRequest,
    VisitorPanelRenderResponse,
    ChatToolbarResponse,
    PluginRenderResponse,
    PluginActionResponse,
    ToolExecuteRequest,
    ToolExecuteResponse,
    InstalledPluginInfo,
    InstalledPluginListResponse,
)
from app.schemas.install import (
    PluginInstallRequest,
    PluginLifecycleResponse,
    PluginLogResponse,
    PluginFetchRequest,
    PluginFetchResponse,
    PluginUpdateCheckResponse,
    PluginUpgradeRequest,
)
from app.core.database import AsyncSessionLocal
from app.models.plugin import InstalledPlugin
from app.services.url_resolver import PluginURLResolver
from sqlalchemy import select

logger = get_logger("api.routes")
router = APIRouter()


# ==================== Plugin List ====================

@router.get("/plugins", response_model=PluginListResponse)
async def list_plugins(project_id: Optional[str] = None) -> PluginListResponse:
    """
    得到所有注册的插件。
    返回一个包含所有当前连接的插件及其功能的列表。
    如果提供了 project_id，则仅返回全局插件和该项目的插件。
    """
    plugins = plugin_manager.get_all_plugins(project_id=project_id)
    return PluginListResponse(plugins=plugins, total=len(plugins))


@router.get("/plugins/installed", response_model=InstalledPluginListResponse)
async def list_installed_plugins(project_id: Optional[str] = None) -> InstalledPluginListResponse:
    """
    得到所有已安装的插件，包括数据库中的已安装插件和当前运行的开发模式插件。
    1. 从数据库中获取已安装的插件。
    2. 从插件管理器中获取当前运行的开发模式插件。
    3. 合并两者，确保没有重复，并返回完整的已安装插件列表。
    如果提供了 project_id，则仅返回该项目的已安装插件和全局插件。
    """
    infos = []
    
    # 1. Get from DB
    async with AsyncSessionLocal() as session:
        stmt = select(InstalledPlugin)
        if project_id:
            stmt = stmt.where(InstalledPlugin.project_id == project_id)
        
        result = await session.execute(stmt)
        db_plugins = result.scalars().all()
        
        for p in db_plugins:
            # Use process manager to get real-time status if available
            status_info = process_manager.get_status(p.plugin_id)
            status = status_info.get("status", p.status)
            pid = status_info.get("pid", p.pid)
            
            # Get capabilities if plugin is connected
            # 给定插件 ID 获取当前连接的插件实例，以便获取其功能列表
            active_plugin = plugin_manager.get_plugin(p.plugin_id)
            capabilities = active_plugin.capabilities if active_plugin else []
            
            infos.append(InstalledPluginInfo(
                id=p.id,
                plugin_id=p.plugin_id,
                name=p.name,
                version=p.version,
                description=p.description,
                author=p.author,
                status=status,
                install_type=p.install_type,
                source_url=p.source_url,
                latest_version=p.latest_version or p.version,
                installed_at=p.installed_at,
                updated_at=p.updated_at,
                pid=pid,
                last_error=p.last_error,
                is_dev_mode=False,
                capabilities=capabilities
            ))

    # 2. Add active dev plugins
    # 添加当前运行的开发模式插件（如果有的话），确保它们也出现在已安装插件列表中
    active_plugins = list(plugin_manager.plugins.values())
    for ap in active_plugins:
        if ap.is_dev_mode:
            # Check project_id filter
            if project_id and ap.project_id != project_id:
                continue
            
            # Check if this dev plugin is already in the list (unlikely but possible)
            if any(info.plugin_id == ap.id for info in infos):
                continue

            infos.append(InstalledPluginInfo(
                id=None,
                plugin_id=ap.id,
                name=ap.name,
                version=ap.version,
                description=ap.description,
                author=ap.author,
                status="running",
                install_type="dev",
                installed_at=ap.connected_at,
                updated_at=ap.connected_at,
                is_dev_mode=True,
                capabilities=ap.capabilities
            ))
            
    return InstalledPluginListResponse(plugins=infos, total=len(infos))

# 抓取插件信息的 API，支持从 GitHub、Gitee 或自定义 URL 获取插件配置。
@router.post("/plugins/fetch-info", response_model=PluginFetchResponse)
async def fetch_plugin_info(request: PluginFetchRequest) -> PluginFetchResponse:
    """
    Fetch plugin information from a URL (GitHub, Gitee, or custom).
    """
    resolver = PluginURLResolver()
    try:
        config = await resolver.resolve(request.url)
        return PluginFetchResponse(**config, source_url=request.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to fetch plugin info from {request.url}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal error fetching plugin info: {e}")


# ==================== Generic Plugin Routes ====================
# 取得特定插件的详细信息，包括其功能和状态。
@router.get("/plugins/{plugin_id}", response_model=PluginInfo)
async def get_plugin(plugin_id: str, project_id: Optional[str] = None) -> PluginInfo:
    """
    Get a specific plugin by ID.
    """
    plugin = plugin_manager.get_plugin(plugin_id, project_id=project_id)
    if not plugin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin not found: {plugin_id}"
        )
    return plugin.to_info()


# ==================== Chat Toolbar ====================
# 得到所有注册的聊天工具栏按钮，供前端在聊天界面中显示。
# 返回一个包含所有按钮的列表，每个按钮对应一个插件提供的功能。
@router.get("/plugins/chat-toolbar/buttons", response_model=ChatToolbarResponse)
async def get_chat_toolbar_buttons(project_id: Optional[str] = None) -> ChatToolbarResponse:
    """
    Get all chat toolbar buttons from registered plugins.
    
    Returns a list of buttons that should be displayed in the chat toolbar.
    """
    buttons = plugin_manager.get_chat_toolbar_buttons(project_id=project_id)
    return ChatToolbarResponse(buttons=buttons)

# 送达插件内容
@router.post("/plugins/chat-toolbar/{plugin_id}/render", response_model=PluginRenderResponse)
async def render_chat_toolbar_plugin(
    plugin_id: str,
    request: PluginRenderRequest,
    project_id: Optional[str] = None,
) -> PluginRenderResponse:
    """
    Render a chat toolbar plugin's content.
    
    Called when user clicks a toolbar button.
    """
    plugin = plugin_manager.get_plugin(plugin_id, project_id=project_id)
    if not plugin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin not found: {plugin_id}"
        )
    
    params = {
        "action_id": request.action_id,
        "visitor_id": request.visitor_id,
        "session_id": request.session_id,
        "visitor": request.visitor.model_dump(exclude_none=True) if request.visitor else None,
        "agent_id": request.agent_id,
        "context": request.context,
        "language": request.language,
    }
    
    result = await plugin_manager.send_request(plugin_id, "chat_toolbar/render", params)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Plugin did not respond in time"
        )
    
    return PluginRenderResponse(**result)

# send_chat_toolbar_event 指定插件 ID 和事件请求，将事件发送到聊天工具栏插件。该 API 用于处理用户与工具栏插件的交互，例如点击按钮或提交表单。
@router.post("/plugins/chat-toolbar/{plugin_id}/event", response_model=PluginActionResponse)
async def send_chat_toolbar_event(
    plugin_id: str,
    request: PluginEventRequest,
    project_id: Optional[str] = None,
) -> PluginActionResponse:
    """
    Send an event to a chat toolbar plugin.
    
    Called when user interacts with the toolbar plugin's UI.
    """
    plugin = plugin_manager.get_plugin(plugin_id, project_id=project_id)
    if not plugin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin not found: {plugin_id}"
        )
    
    params = {
        "event_type": request.event_type,
        "action_id": request.action_id,
        "visitor_id": request.visitor_id,
        "session_id": request.session_id,
        "selected_id": request.selected_id,
        "language": request.language,
        "form_data": request.form_data,
        "payload": request.payload,
    }
    
    result = await plugin_manager.send_request(plugin_id, "chat_toolbar/event", params)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Plugin did not respond in time"
        )
    
    return PluginActionResponse(**result)


# ==================== Visitor Panel ====================
# render_visitor_panels 接收一个 VisitorPanelRenderRequest 请求，并返回所有支持访客面板的插件渲染结果。该 API 用于在访客界面中显示插件提供的面板内容。
@router.post("/plugins/visitor-panel/render", response_model=VisitorPanelRenderResponse)
async def render_visitor_panels(
    request: VisitorPanelRenderRequest,
    project_id: Optional[str] = None,
) -> VisitorPanelRenderResponse:
    """
    Render all visitor panel plugins for a specific visitor.
    
    Returns a list of rendered panels from all plugins that support visitor_panel.
    """
    panels = await plugin_manager.render_visitor_panels(
        visitor_id=request.visitor_id,
        session_id=request.session_id,
        visitor=request.visitor,
        context=request.context or {},
        language=request.language,
        project_id=project_id,
    )
    return VisitorPanelRenderResponse(panels=panels)


# ==================== Generic Plugin Routes ====================

@router.post("/plugins/{plugin_id}/render", response_model=PluginRenderResponse)
async def render_plugin(
    plugin_id: str, 
    request: PluginRenderRequest,
    project_id: Optional[str] = None,
) -> PluginRenderResponse:
    """
    Trigger a plugin to render its UI.
    
    Sends a render request to the plugin and returns the JSON-UI response.
    """
    plugin = plugin_manager.get_plugin(plugin_id, project_id=project_id)
    if not plugin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin not found: {plugin_id}"
        )
    
    # Determine the render method based on plugin capabilities
    method = "visitor_panel/render"
    for cap in plugin.capabilities:
        if cap.type == "chat_toolbar":
            method = "chat_toolbar/render"
            break
    
    params = {
        "visitor_id": request.visitor_id,
        "session_id": request.session_id,
        "visitor": request.visitor.model_dump(exclude_none=True) if request.visitor else None,
        "agent_id": request.agent_id,
        "action_id": request.action_id,
        "context": request.context,
        "language": request.language,
    }
    
    result = await plugin_manager.send_request(plugin_id, method, params)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Plugin did not respond in time"
        )
    
    return PluginRenderResponse(**result)


@router.post("/plugins/{plugin_id}/event", response_model=PluginActionResponse)
async def send_plugin_event(
    plugin_id: str, 
    request: PluginEventRequest,
    project_id: Optional[str] = None,
) -> PluginActionResponse:
    """
    送达事件到插件。
    使用于用户与插件 UI 的交互（按钮点击、表单提交等）。
    返回 JSON-ACTION 响应。
    """
    plugin = plugin_manager.get_plugin(plugin_id, project_id=project_id)
    if not plugin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin not found: {plugin_id}"
        )
    
    # Determine the event method based on plugin capabilities or explicit extension_type
    method = None
    if request.extension_type:
        method = f"{request.extension_type}/event"
    else:
        # Fallback to guessing (backward compatibility)
        method = "visitor_panel/event"
        for cap in plugin.capabilities:
            if cap.type == "chat_toolbar":
                method = "chat_toolbar/event"
                break
    
    params = {
        "event_type": request.event_type,
        "action_id": request.action_id,
        "visitor_id": request.visitor_id,
        "session_id": request.session_id,
        "selected_id": request.selected_id,
        "language": request.language,
        "form_data": request.form_data,
        "payload": request.payload,
    }
    
    result = await plugin_manager.send_request(plugin_id, method, params)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Plugin did not respond in time"
        )
    
    return PluginActionResponse(**result)


# ==================== Tool Execution (MCP) ====================

@router.post("/plugins/tools/execute/{plugin_id}/{tool_name}", response_model=ToolExecuteResponse)
# execute_plugin_tool 接收一个 ToolExecuteRequest 请求，并将其发送到指定插件的工具执行接口。该 API 用于执行插件提供的 MCP 工具，并返回工具执行结果。
async def execute_plugin_tool(
    plugin_id: str,
    tool_name: str,
    request: ToolExecuteRequest,
    project_id: Optional[str] = None,
) -> ToolExecuteResponse:
    """
    Execute an MCP tool provided by a plugin.
    """
    plugin = plugin_manager.get_plugin(plugin_id, project_id=project_id)
    if not plugin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin not found: {plugin_id}"
        )
    
    params = {
        "tool_name": tool_name,
        "arguments": request.arguments,
        "visitor_id": request.context.visitor_id,
        "session_id": request.context.session_id,
        "agent_id": request.context.agent_id,
        "language": request.context.language,
    }
    
    result = await plugin_manager.send_request(plugin_id, "tool/execute", params)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Plugin did not respond in time"
        )
    
    return ToolExecuteResponse(**result)


# ==================== Installation & Lifecycle ====================

# ==================== Installation & Lifecycle ====================

@router.post("/plugins/install-stream")
# install_plugin_stream 接收一个 PluginInstallRequest 请求，并在安装插件的过程中通过 Server-Sent Events (SSE) 实时推送安装进度。该 API 用于前端在安装插件时显示实时进度和状态。
async def install_plugin_stream(request: PluginInstallRequest):
    """
    Install a plugin and stream progress via SSE.
    """
    async def event_generator():
        queue = asyncio.Queue()

        async def progress_callback(stage: str, message: str):
            await queue.put({"stage": stage, "message": message})

        # Run installation in background
        async def run_install():
            try:
                # 1. Update DB to installing status
                async with AsyncSessionLocal() as session:
                    stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == request.id)
                    result = await session.execute(stmt)
                    existing = result.scalar_one_or_none()
                    
                    if existing:
                        plugin = existing
                        plugin.name = request.name
                        plugin.version = request.version
                        plugin.latest_version = request.version
                        plugin.description = request.description
                        plugin.author = request.author
                        plugin.source_url = request.source_url
                        plugin.status = "installing"
                    else:
                        plugin = InstalledPlugin(
                            plugin_id=request.id,
                            project_id=request.project_id,
                            name=request.name,
                            version=request.version,
                            latest_version=request.version,
                            description=request.description,
                            author=request.author,
                            source_url=request.source_url,
                            install_type="github" if request.source.github else "binary",
                            source_config=request.source.model_dump(exclude_none=True),
                            build_config=request.build.model_dump(exclude_none=True) if request.build else None,
                            runtime_config=request.runtime.model_dump(exclude_none=True),
                            status="installing"
                        )
                        session.add(plugin)
                    
                    await session.commit()

                # 2. Run actual installation
                success, message, install_path = await installer.install(request, progress_callback=progress_callback)

                # 3. Update DB with results
                async with AsyncSessionLocal() as session:
                    stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == request.id)
                    result = await session.execute(stmt)
                    plugin = result.scalar_one_or_none()
                    
                    if success:
                        plugin.status = "stopped"
                        plugin.install_path = install_path
                        await session.commit()
                        
                        # Auto-start
                        await queue.put({"stage": "starting", "message": "Starting plugin process..."})
                        await process_manager.start_plugin(plugin.plugin_id, request.model_dump())
                        
                        await queue.put({"stage": "complete", "message": "Installation successful"})
                    else:
                        plugin.status = "error"
                        plugin.last_error = message
                        await session.commit()
                        await queue.put({"stage": "error", "message": message})
            except Exception as e:
                logger.error(f"Error in install-stream for {request.id}: {e}")
                await queue.put({"stage": "error", "message": str(e)})
            finally:
                # Signal end of stream
                await queue.put(None)

        # Start installation
        asyncio.create_task(run_install())

        # Stream progress from queue
        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/plugins/install", response_model=InstalledPluginInfo)


@router.delete("/plugins/{plugin_id}/uninstall", response_model=Dict[str, Any])
async def uninstall_plugin(plugin_id: str, project_id: Optional[str] = None):
    """
    Uninstall a plugin.
    """
    async with AsyncSessionLocal() as session:
        stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == plugin_id)
        if project_id:
            stmt = stmt.where(InstalledPlugin.project_id == project_id)
        
        result = await session.execute(stmt)
        plugin = result.scalar_one_or_none()
        
        if not plugin:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Plugin {plugin_id} not found in database for this project"
            )
        
        # Stop process
        await process_manager.stop_plugin(plugin_id)
        
        # Remove files
        await installer.uninstall(plugin_id)
        
        # Remove from DB
        await session.delete(plugin)
        await session.commit()
        
        return {"success": True, "message": "Plugin uninstalled"}


@router.post("/plugins/{plugin_id}/start", response_model=PluginLifecycleResponse)
async def start_plugin(
    plugin_id: str, 
    request: Optional[Dict[str, Any]] = None,
    project_id: Optional[str] = None
):
    """
    Start a plugin process.
    """
    config = None
    # If a full config is provided in the request body, use it
    if request and "id" in request and "source" in request:
        config = request
    else:
        # Fetch from DB
        async with AsyncSessionLocal() as session:
            stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == plugin_id)
            if project_id:
                stmt = stmt.where(InstalledPlugin.project_id == project_id)
                
            result = await session.execute(stmt)
            plugin = result.scalar_one_or_none()
            if not plugin:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Plugin {plugin_id} not found in database for this project"
                )
            config = {
                "id": plugin.plugin_id,
                "project_id": str(plugin.project_id),
                "name": plugin.name,
                "version": plugin.version,
                "description": plugin.description,
                "author": plugin.author,
                "source": plugin.source_config,
                "build": plugin.build_config,
                "runtime": plugin.runtime_config
            }
            
    success, message = await process_manager.start_plugin(plugin_id, config)
    status_info = process_manager.get_status(plugin_id)
    
    return PluginLifecycleResponse(
        success=success,
        message=message,
        status=status_info.get("status"),
        pid=status_info.get("pid")
    )


@router.post("/plugins/{plugin_id}/stop", response_model=PluginLifecycleResponse)
async def stop_plugin(plugin_id: str, project_id: Optional[str] = None):
    """
    Stop a plugin process.
    """
    # Verify ownership
    async with AsyncSessionLocal() as session:
        stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == plugin_id)
        if project_id:
            stmt = stmt.where(InstalledPlugin.project_id == project_id)
        result = await session.execute(stmt)
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Plugin not found for this project")

    success = await process_manager.stop_plugin(plugin_id)
    status_info = process_manager.get_status(plugin_id)
    
    return PluginLifecycleResponse(
        success=success,
        message="Stopped" if success else "Failed to stop",
        status=status_info.get("status"),
        pid=None
    )


@router.post("/plugins/{plugin_id}/restart", response_model=PluginLifecycleResponse)
async def restart_plugin(plugin_id: str, project_id: Optional[str] = None):
    """
    Restart a plugin process.
    """
    # Verify ownership
    async with AsyncSessionLocal() as session:
        stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == plugin_id)
        if project_id:
            stmt = stmt.where(InstalledPlugin.project_id == project_id)
        result = await session.execute(stmt)
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Plugin not found for this project")

    success, message = await process_manager.restart_plugin(plugin_id)
    status_info = process_manager.get_status(plugin_id)
    
    return PluginLifecycleResponse(
        success=success,
        message=message,
        status=status_info.get("status"),
        pid=status_info.get("pid")
    )


@router.get("/plugins/{plugin_id}/logs", response_model=PluginLogResponse)
async def get_plugin_logs(plugin_id: str, project_id: Optional[str] = None):
    """
    Get plugin logs.
    """
    # Verify ownership
    async with AsyncSessionLocal() as session:
        stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == plugin_id)
        if project_id:
            stmt = stmt.where(InstalledPlugin.project_id == project_id)
        result = await session.execute(stmt)
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Plugin not found for this project")

    logs = process_manager.get_logs(plugin_id)
    return PluginLogResponse(plugin_id=plugin_id, logs=logs)


@router.get("/plugins/{plugin_id}/status", response_model=Dict[str, Any])
async def get_plugin_status(plugin_id: str, project_id: Optional[str] = None):
    """
    Get detailed plugin status.
    """
    # Verify ownership
    async with AsyncSessionLocal() as session:
        stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == plugin_id)
        if project_id:
            stmt = stmt.where(InstalledPlugin.project_id == project_id)
        result = await session.execute(stmt)
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Plugin not found for this project")

    return process_manager.get_status(plugin_id)


@router.get("/plugins/{plugin_id}/check-update", response_model=PluginUpdateCheckResponse)
async def check_plugin_update(plugin_id: str, project_id: Optional[str] = None) -> PluginUpdateCheckResponse:
    """
    Check if an update is available for an installed plugin.
    """
    async with AsyncSessionLocal() as session:
        stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == plugin_id)
        if project_id:
            stmt = stmt.where(InstalledPlugin.project_id == project_id)
        
        result = await session.execute(stmt)
        plugin = result.scalar_one_or_none()
        
        if not plugin:
            raise HTTPException(status_code=404, detail="Plugin not found")
        
        if not plugin.source_url:
            return PluginUpdateCheckResponse(
                has_update=False,
                current_version=plugin.version,
                latest_version=plugin.version,
                message="No source URL found for this plugin, cannot check for updates."
            )
        
        resolver = PluginURLResolver()
        try:
            latest_config_dict = await resolver.resolve(plugin.source_url)
            latest_config = PluginFetchResponse(**latest_config_dict, source_url=plugin.source_url)
            
            # Simple version comparison
            has_update = latest_config.version != plugin.version
            
            # Save latest version to DB
            plugin.latest_version = latest_config.version
            await session.commit()
            
            return PluginUpdateCheckResponse(
                has_update=has_update,
                current_version=plugin.version,
                latest_version=latest_config.version,
                latest_config=latest_config
            )
        except Exception as e:
            logger.error(f"Failed to check update for {plugin_id}: {e}")
            return PluginUpdateCheckResponse(
                has_update=False,
                current_version=plugin.version,
                latest_version=plugin.version,
                message=f"Error checking update: {str(e)}"
            )


@router.post("/plugins/{plugin_id}/upgrade")
async def upgrade_plugin(
    plugin_id: str, 
    request: PluginUpgradeRequest,
    project_id: Optional[str] = None
):
    """
    Upgrade an installed plugin and stream progress via SSE.
    """
    async def event_generator():
        queue = asyncio.Queue()

        async def progress_callback(stage: str, message: str):
            await queue.put({"stage": stage, "message": message})

        async def run_upgrade():
            try:
                # 1. Get existing plugin
                async with AsyncSessionLocal() as session:
                    stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == plugin_id)
                    if project_id:
                        stmt = stmt.where(InstalledPlugin.project_id == project_id)
                    result = await session.execute(stmt)
                    plugin = result.scalar_one_or_none()
                    
                    if not plugin:
                        await queue.put({"stage": "error", "message": "Plugin not found"})
                        return

                # 2. Stop existing process
                await progress_callback("stopping", "Stopping plugin process...")
                await process_manager.stop_plugin(plugin_id)

                # 3. Create InstallRequest for installer
                from sqlalchemy import func
                install_request = PluginInstallRequest(
                    id=plugin_id,
                    project_id=str(plugin.project_id),
                    name=request.latest_config.name,
                    version=request.latest_config.version,
                    description=request.latest_config.description,
                    author=request.latest_config.author,
                    source=request.latest_config.source,
                    source_url=request.latest_config.source_url,
                    build=request.latest_config.build,
                    runtime=request.latest_config.runtime
                )

                # 4. Run upgrade (with backup/rollback support in installer)
                success, message, install_path = await installer.upgrade(install_request, progress_callback=progress_callback)

                # 5. Update DB and start
                async with AsyncSessionLocal() as session:
                    stmt = select(InstalledPlugin).where(InstalledPlugin.plugin_id == plugin_id)
                    result = await session.execute(stmt)
                    plugin = result.scalar_one_or_none()
                    
                    if success:
                        plugin.name = install_request.name
                        plugin.version = install_request.version
                        plugin.description = install_request.description
                        plugin.author = install_request.author
                        plugin.latest_version = install_request.version
                        plugin.status = "stopped"
                        plugin.install_path = install_path
                        plugin.updated_at = func.now()
                        await session.commit()
                        
                        await progress_callback("starting", "Starting upgraded plugin...")
                        await process_manager.start_plugin(plugin_id, install_request.model_dump())
                        await progress_callback("complete", "Upgrade successful")
                    else:
                        plugin.status = "error"
                        plugin.last_error = message
                        await session.commit()
                        await progress_callback("error", message)
                        
                        # Try to restart old version if rollback was successful
                        await progress_callback("restarting", "Restarting original version...")
                        await process_manager.start_plugin(plugin_id)

            except Exception as e:
                logger.error(f"Error in upgrade-stream for {plugin_id}: {e}")
                await queue.put({"stage": "error", "message": str(e)})
            finally:
                await queue.put(None)

        asyncio.create_task(run_upgrade())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

