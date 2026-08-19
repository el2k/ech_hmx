"""Plugin Manager - Registry and request dispatcher."""

from __future__ import annotations

import asyncio
import json
import struct
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from jose import jwt, JWTError

from app.config import settings
from app.core.logging import get_logger
from app.schemas.plugin import (
    PluginCapability,
    PluginInfo,
    ChatToolbarButton,
    PluginPanelItem,
    PluginRenderResponse,
    VisitorInfo,
)

logger = get_logger("services.plugin_manager")

# 插件连接
@dataclass
class PluginConnection:
    """Represents a connected plugin."""
    id: str
    name: str
    version: str
    description: Optional[str] = None
    author: Optional[str] = None
    capabilities: List[PluginCapability] = field(default_factory=list)
    connected_at: datetime = field(default_factory=datetime.utcnow)
    reader: Optional[asyncio.StreamReader] = None
    writer: Optional[asyncio.StreamWriter] = None
    project_id: Optional[str] = None  # Associated project ID (for dev mode)
    is_dev_mode: bool = False         # Whether plugin is in dev mode
    dev_user_id: Optional[str] = None # User who owns the dev connection
    _request_id: int = 0
    _pending_requests: Dict[int, asyncio.Future] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id
    # 返回插件信息
    def to_info(self) -> PluginInfo:
        return PluginInfo(
            id=self.id,
            name=self.name,
            version=self.version,
            description=self.description,
            author=self.author,
            capabilities=self.capabilities,
            connected_at=self.connected_at,
            status="connected" if self.writer and not self.writer.is_closing() else "disconnected",
            is_dev_mode=self.is_dev_mode
        )
# 插件管理
class PluginManager:
    """
    单例插件管理器。
    管理插件连接、注册和请求分发。
    """
    _instance: Optional["PluginManager"] = None
    '''
    __new__ 是 Python 对象构建的魔术方法：负责创建对象，在 __init__ 之前执行。
    def __new__(cls)
    参数cls自动传入，就是 PluginManager 类。
    相当于：cls = PluginManager
    if cls._instance is None:
    cls._instance，访问类的静态属性 _instance，保存唯一的实例对象。
    不要写成 self._instance，对象还没创建出来，此时还没有 self。
    cls._instance = super().__new__(cls)
    super().__new__(cls)：调用父类 (object) 底层 C 逻辑，真正分配内存，生成一个 PluginManager 实例对象。
    把生成出来的唯一实例，存到类属性 _instance。
    cls._instance._initialized = False
    给刚刚创建出来的实例对象，增加实例属性_initialized=False，标记还没完成初始化。
    return cls._instance
    每次 PluginManager() 去 new 对象，永远返回同一个实例，实现单例模式。'''
    def __new__(cls) -> "PluginManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        # _plugins 指向一个字典，键是插件 ID，值是 PluginConnection 对象，保存所有注册的插件连接。
        self._plugins: Dict[str, PluginConnection] = {}
        # _lock 是一个 asyncio.Lock 异步锁，用于保护 _plugins 的并发访问，避免多个协程同时修改插件注册表。
        self._lock = asyncio.Lock()
        # _tool_sync 是一个可选的工具同步服务引用，用于在插件注册时同步工具到 tgo-ai。初始为 None，稍后通过 set_tool_sync 方法设置。
        self._tool_sync = None  # Will be set after import to avoid circular imports
        logger.info("PluginManager initialized")

    def set_tool_sync(self, tool_sync):
        """Set the tool sync service."""
        self._tool_sync = tool_sync

    @property
    def plugins(self) -> Dict[str, PluginConnection]:
        return self._plugins
    # 注册一个新的插件连接
    async def register(
        self,
        name: str,
        version: str,
        capabilities: List[Dict[str, Any]],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        plugin_id: Optional[str] = None,
        description: Optional[str] = None,
        author: Optional[str] = None,
        dev_token: Optional[str] = None,
        is_tcp: bool = False,
    ) -> Tuple[str, PluginConnection]:
        """Register a new plugin connection."""
        if not plugin_id:
            plugin_id = f"plugin_{uuid.uuid4().hex[:8]}"
        
        caps = [PluginCapability(**c) for c in capabilities]
        
        project_id = None
        is_dev_mode = False
        dev_user_id = None
        
        # 1. Try to identify by dev_token first
        # 尝试通过 dev_token 识别插件身份
        # MCP 插件注册接入阶段，校验开发者调试令牌 (dev_token)，区分「开发模式插件」和正式插件。
        '''
        收到插件注册请求 → 是否携带dev_token？
        ├─否 → 走正式插件注册流程
        └─是 → jwt.decode校验签名
            ├─签名失败(篡改/过期) → 打警告日志，抛出异常，拒绝注册
            └─签名成功
                ├─payload.type != plugin_dev → 拒绝注册
                └─payload.type == plugin_dev → 开启开发模式，完成调试插件注册'''
        if dev_token:
            try:
                payload = jwt.decode(dev_token, settings.SECRET_KEY, algorithms=["HS256"])
                if payload.get("type") == "plugin_dev":
                    project_id = payload.get("project_id")
                    dev_user_id = payload.get("user_id")
                    is_dev_mode = True
                    logger.info(f"Plugin {plugin_id} registered in DEV mode for project {project_id}")
                else:
                    logger.warning(f"Registration rejected for {plugin_id}: invalid token type")
                    raise ValueError("Invalid dev_token type")
            except JWTError as e:
                logger.warning(f"Registration rejected for {plugin_id}: token verification failed: {e}")
                raise ValueError(f"Invalid dev_token: {str(e)}")
        
        # 2. If not dev mode, check if it's an installed plugin in DB
        # 如果没有开启开发模式，尝试在数据库中查找插件的安装记录，确认它是否是已安装的插件。
        if not is_dev_mode and plugin_id:
            try:
                from sqlalchemy import select
                from app.core.database import AsyncSessionLocal
                from app.models.plugin import InstalledPlugin
                
                async with AsyncSessionLocal() as session:
                    stmt = select(InstalledPlugin.project_id).where(InstalledPlugin.plugin_id == plugin_id)
                    result = await session.execute(stmt)
                    db_project_id = result.scalar_one_or_none()
                    if db_project_id:
                        project_id = str(db_project_id)
                        logger.info(f"Plugin {plugin_id} identified as installed plugin for project {project_id}")
            except Exception as e:
                # Table might not exist yet
                if "pg_installed_plugins" in str(e):
                    logger.info(f"Table pg_installed_plugins does not exist yet, skipping lookup for {plugin_id}")
                else:
                    logger.error(f"Error checking installed plugin {plugin_id}: {e}")

        # 3. Final check for debug connection security
        # Requirement: If connecting via TCP and not recognized as an installed plugin, 
        # it MUST have had a valid dev_token (which would have set is_dev_mode to True).
        # 最终检查为了安全性：如果是 TCP 连接且不是已安装插件，则必须是开发模式插件，否则拒绝注册。
        if is_tcp and not is_dev_mode and not project_id:
            logger.warning(f"Registration rejected for {plugin_id}: unknown TCP connection requires dev_token")
            raise ValueError("Debug connection requires dev_token")
        
        plugin = PluginConnection(
            id=plugin_id,
            name=name,
            version=version,
            description=description,
            author=author,
            capabilities=caps,
            reader=reader,
            writer=writer,
            project_id=project_id,
            is_dev_mode=is_dev_mode,
            dev_user_id=dev_user_id,
        )
        # 添加到插件注册表
        async with self._lock:
            self._plugins[plugin_id] = plugin
        
        logger.info(
            f"Plugin registered: {name} v{version} (id={plugin_id})",
            extra={"plugin_id": plugin_id, "capabilities": [c.type for c in caps]}
        )
        
        # Sync tools to tgo-ai if mcp_tools capability is present
        # 如果插件具有 mcp_tools 能力，则同步工具到 tgo-ai
        if self._tool_sync:
            asyncio.create_task(self._tool_sync.sync_plugin_tools(plugin))
        
        return plugin_id, plugin
    # 注销插件
    async def unregister(self, plugin_id: str):
        """Unregister a plugin."""
        async with self._lock:
            plugin = self._plugins.pop(plugin_id, None)
        
        if plugin:
            logger.info(f"Plugin unregistered: {plugin.name} (id={plugin_id})")
            
            # Remove tools from tgo-ai
            # 如果插件具有 mcp_tools 能力，则从 tgo-ai 移除工具
            if self._tool_sync:
                asyncio.create_task(self._tool_sync.remove_plugin_tools(plugin_id))
            
            # Cancel pending requests
            for future in plugin._pending_requests.values():
                if not future.done():
                    future.cancel()
            # Close writer
            if plugin.writer and not plugin.writer.is_closing():
                plugin.writer.close()
                try:
                    await plugin.writer.wait_closed()
                except Exception:
                    pass
    # 获取插件信息                
    def get_plugin(self, plugin_id: str, project_id: Optional[str] = None) -> Optional[PluginConnection]:
        """Get a plugin by ID, optionally verifying project association."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return None
            
        # If project_id is provided, verify association
        if project_id and plugin.project_id and plugin.project_id != project_id:
            logger.warning(f"Project {project_id} attempted to access plugin {plugin_id} associated with {plugin.project_id}")
            return None
            
        return plugin
    # 获取所有插件信息
    def get_all_plugins(self, project_id: Optional[str] = None) -> List[PluginInfo]:
        """Get all registered plugins, optionally filtered by project ID."""
        if not project_id:
            return [p.to_info() for p in self._plugins.values()]
        
        # Filter plugins:
        # 1. Global plugins (project_id is None)
        # 2. Plugins specifically for this project
        result = []
        for p in self._plugins.values():
            if p.project_id is None or p.project_id == project_id:
                result.append(p.to_info())
        return result
    # 获取支持特定扩展类型的插件
    def get_plugins_by_type(self, extension_type: str, project_id: Optional[str] = None) -> List[PluginConnection]:
        """Get plugins that support a specific extension type, filtered by project."""
        result = []
        for plugin in self._plugins.values():
            # Check project association
            if project_id and plugin.project_id and plugin.project_id != project_id:
                continue
                
            for cap in plugin.capabilities:
                # 如果插件的能力类型与指定的扩展类型匹配，则将该插件添加到结果列表中
                if cap.type == extension_type:
                    result.append(plugin)
                    break
        return result
    # 获取所有聊天工具栏按钮
    def get_chat_toolbar_buttons(self, project_id: Optional[str] = None) -> List[ChatToolbarButton]:
        """Get all chat toolbar buttons from registered plugins, filtered by project."""
        buttons = []
        for plugin in self._plugins.values():
            # Check project association
            if project_id and plugin.project_id and plugin.project_id != project_id:
                continue
                
            for cap in plugin.capabilities:
                if cap.type == "chat_toolbar":
                    # 如果插件的能力类型是 "chat_toolbar"，则创建一个 ChatToolbarButton 对象，并将其添加到按钮列表中
                    buttons.append(ChatToolbarButton(
                        plugin_id=plugin.id,
                        title=cap.title,
                        icon=cap.icon,
                        tooltip=cap.tooltip,
                        shortcut=cap.shortcut,
                    ))
        return buttons
    # 发送请求到插件
    async def send_request(
        self,
        plugin_id: str,
        method: str,
        params: Dict[str, Any],
        timeout: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Send a JSON-RPC request to a plugin and wait for response.
        
        Returns the result dict or None on error.
        """
        plugin = self.get_plugin(plugin_id)
        if not plugin or not plugin.writer or plugin.writer.is_closing():
            logger.warning(f"Plugin not available: {plugin_id}")
            return None

        timeout = timeout or settings.PLUGIN_REQUEST_TIMEOUT
        request_id = plugin.next_request_id()
        
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        # Create future for response
        # future 是一个 asyncio.Future 对象，用于等待插件的响应。将其存储在插件的 _pending_requests 字典中，以便在收到响应时可以找到对应的 future 并设置结果。
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        plugin._pending_requests[request_id] = future

        try:
            # Send message
            await self._send_message(plugin.writer, request)
            
            # Wait for response
            # 等待插件的响应，使用 asyncio.wait_for 设置超时时间。如果在指定时间内没有收到响应，将引发 asyncio.TimeoutError 异常。
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.error(f"Plugin request timeout: {plugin_id} {method}")
            return None
        except Exception as e:
            logger.error(f"Plugin request error: {plugin_id} {method}: {e}")
            return None
        finally:
            plugin._pending_requests.pop(request_id, None)
    # 处理插件响应
    async def handle_response(self, plugin: PluginConnection, message: Dict[str, Any]):
        """Handle a JSON-RPC response from a plugin."""
        request_id = message.get("id")
        if request_id is None:
            return

        future = plugin._pending_requests.get(request_id)
        if future and not future.done():
            if "error" in message:
                error = message["error"]
                logger.warning(f"Plugin error response: {error}")
                future.set_result(None)
            else:
                # 否则将响应结果设置为 future 的结果，通知等待的协程继续执行。
                # 协程 A 被唤醒，拿到数据，继续执行。
                future.set_result(message.get("result"))

    async def _send_message(self, writer: asyncio.StreamWriter, message: Dict[str, Any]):
        """Send a length-prefixed JSON message."""
        json_bytes = json.dumps(message, ensure_ascii=False).encode("utf-8")
        # length_prefix 是一个 4 字节的二进制数据，表示 JSON 消息的长度（大端字节序）。将长度前缀和 JSON 消息一起写入 writer，以便接收方知道消息的边界。
        length_prefix = struct.pack(">I", len(json_bytes))
        writer.write(length_prefix + json_bytes)
        await writer.drain()
    # 渲染访客面板插件
    async def render_visitor_panels(
        self,
        visitor_id: str,
        session_id: Optional[str],
        visitor: Optional[VisitorInfo],
        context: Dict[str, Any],
        language: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[PluginPanelItem]:
        """
        Render all visitor panel plugins.
        
        Returns list of PluginPanelItem.
        """
        plugins = self.get_plugins_by_type("visitor_panel", project_id=project_id)
        if not plugins:
            return []

        params = {
            "visitor_id": visitor_id,
            "session_id": session_id,
            "visitor": visitor.model_dump(exclude_none=True) if visitor else {},
            "context": context,
            "language": language,
        }
        # render_one 是一个内部异步函数，用于向单个插件发送渲染请求，并将响应解析为 PluginPanelItem 对象。如果插件返回有效的渲染响应，则创建 PluginPanelItem 并返回；否则返回 None。
        async def render_one(plugin: PluginConnection) -> Optional[PluginPanelItem]:
            result = await self.send_request(plugin.id, "visitor_panel/render", params)
            if result:
                try:
                    ui_resp = PluginRenderResponse(**result)
                    cap = next((c for c in plugin.capabilities if c.type == "visitor_panel"), None)
                    return PluginPanelItem(
                        plugin_id=plugin.id,
                        title=cap.title if cap else plugin.name,
                        icon=cap.icon if cap else None,
                        priority=cap.priority if cap else 10,
                        ui=ui_resp,
                    )
                except Exception as e:
                    logger.error(f"Failed to parse plugin render response from {plugin.id}: {e}")
                    return None
            return None

        tasks = [render_one(p) for p in plugins]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        panels = []
        for r in results:
            if isinstance(r, PluginPanelItem):
                panels.append(r)
            elif isinstance(r, Exception):
                logger.error(f"Error rendering visitor panel: {r}")

        panels.sort(key=lambda x: x.priority)
        return panels
    # 关闭所有插件连接
    async def shutdown_all(self):
        """Shutdown all plugin connections gracefully."""
        logger.info(f"Shutting down {len(self._plugins)} plugins...")
        
        async def shutdown_one(plugin_id: str, plugin: PluginConnection):
            try:
                await self.send_request(plugin_id, "shutdown", {}, timeout=5)
            except Exception:
                pass
            await self.unregister(plugin_id)

        tasks = [shutdown_one(pid, p) for pid, p in list(self._plugins.items())]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info("All plugins shut down")


# Global singleton instance
plugin_manager = PluginManager()

