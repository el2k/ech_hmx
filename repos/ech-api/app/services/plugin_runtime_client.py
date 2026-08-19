# =============================================================================
# 模块：插件运行时客户端 (Plugin Runtime Client)
# =============================================================================
# 该模块提供了与 tgo-plugin-runtime 微服务通信的 HTTP 客户端，主要包括：
# 1. 插件管理（列表、获取、安装、卸载、启动、停止、重启）
# 2. 聊天工具栏插件（获取按钮、渲染内容、发送事件）
# 3. 访客面板插件（渲染所有面板）
# 4. 通用插件路由（渲染、事件）
# 5. 工具执行（MCP 工具调用）
# 6. 插件状态和日志查询
# 
# 设计目的：
# - 封装与插件运行时服务的 HTTP 通信细节
# - 提供统一的接口供其他模块调用
# - 支持插件的完整生命周期管理
# 
# 依赖服务：tgo-plugin-runtime（插件运行时微服务）
# =============================================================================

from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("services.plugin_runtime_client")


# =============================================================================
# 插件运行时客户端类
# =============================================================================

class PluginRuntimeClient:
    """
    HTTP 客户端，用于与 tgo-plugin-runtime 服务通信。

    功能分组：
    1. 插件列表管理：列出、获取插件信息
    2. 聊天工具栏：获取按钮、渲染内容、处理事件
    3. 访客面板：渲染所有访客面板插件
    4. 通用插件操作：渲染、事件、工具执行
    5. 插件生命周期：安装、卸载、启动、停止、重启
    6. 插件监控：获取状态、日志、检查更新

    配置来源：
    - base_url: 从环境变量 PLUGIN_RUNTIME_URL 读取
    - timeout: 从环境变量 PLUGIN_RUNTIME_TIMEOUT 读取
    """

    def __init__(self):
        """初始化插件运行时客户端。"""
        self.base_url = settings.PLUGIN_RUNTIME_URL.rstrip("/")
        self.timeout = settings.PLUGIN_RUNTIME_TIMEOUT

    # =========================================================================
    # 内部请求方法
    # =========================================================================

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        向插件运行时服务发起 HTTP 请求的内部方法。

        执行流程：
        1. 拼接完整的请求 URL
        2. 使用 httpx.AsyncClient 发起异步 HTTP 请求
        3. 检查响应状态码（404 返回 None，4xx/5xx 抛出异常）
        4. 解析并返回 JSON 响应

        错误处理：
        - HTTPStatusError: 服务返回错误状态码（4xx/5xx）
        - RequestError: 网络连接错误

        Args:
            method: HTTP 方法
            path: API 路径
            json: JSON 请求体
            params: URL 查询参数

        Returns:
            Optional[Dict[str, Any]]: 解析后的 JSON 响应，404 返回 None

        Raises:
            httpx.HTTPStatusError: HTTP 错误响应（非 404）
            httpx.RequestError: 连接错误
        """
        url = f"{self.base_url}{path}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                    headers={"Content-Type": "application/json"},
                )

                # 404 表示资源不存在，返回 None
                if response.status_code == 404:
                    return None

                # 其他错误状态码抛出异常
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Plugin runtime HTTP error: {e.response.status_code} {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Plugin runtime request error: {e}")
            raise

    # =========================================================================
    # 1. 插件列表管理
    # =========================================================================

    async def list_plugins(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取所有已注册的插件列表。

        Args:
            project_id: 项目 ID（可选，用于过滤）

        Returns:
            Dict[str, Any]: 包含 plugins 和 total 的响应
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request("GET", "/plugins", params=params) or {"plugins": [], "total": 0}

    async def get_plugin(self, plugin_id: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        根据 ID 获取特定插件的详细信息。

        Args:
            plugin_id: 插件 ID
            project_id: 项目 ID（可选，用于权限验证）

        Returns:
            Optional[Dict[str, Any]]: 插件信息，不存在时返回 None
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request("GET", f"/plugins/{plugin_id}", params=params)

    # =========================================================================
    # 2. 聊天工具栏插件
    # =========================================================================

    async def get_chat_toolbar_buttons(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """
        从所有插件获取聊天工具栏按钮。

        聊天工具栏按钮显示在聊天界面的工具栏区域，
        用户点击后可触发插件功能。

        Args:
            project_id: 项目 ID（可选，用于过滤）

        Returns:
            Dict[str, Any]: 包含 buttons 列表的响应
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request("GET", "/plugins/chat-toolbar/buttons", params=params) or {"buttons": []}

    async def render_chat_toolbar(
        self,
        plugin_id: str,
        request_data: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        渲染聊天工具栏插件内容。

        当用户点击工具栏按钮时，调用此方法获取插件渲染的 UI 内容。

        Args:
            plugin_id: 插件 ID
            request_data: 请求数据（包含上下文信息）
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 渲染结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "POST",
            f"/plugins/chat-toolbar/{plugin_id}/render",
            json=request_data,
            params=params,
        )

    async def send_chat_toolbar_event(
        self,
        plugin_id: str,
        request_data: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        向聊天工具栏插件发送事件。

        用于处理用户在插件 UI 中的交互操作。

        Args:
            plugin_id: 插件 ID
            request_data: 事件数据
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 事件处理结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "POST",
            f"/plugins/chat-toolbar/{plugin_id}/event",
            json=request_data,
            params=params,
        )

    # =========================================================================
    # 3. 访客面板插件
    # =========================================================================

    async def render_visitor_panels(
        self,
        request_data: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        渲染所有访客面板插件。

        访客面板显示在客服界面的侧边栏，展示访客相关信息。

        Args:
            request_data: 请求数据（包含访客信息）
            project_id: 项目 ID（可选）

        Returns:
            Dict[str, Any]: 包含 panels 列表的响应
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "POST",
            "/plugins/visitor-panel/render",
            json=request_data,
            params=params,
        ) or {"panels": []}

    # =========================================================================
    # 4. 通用插件路由
    # =========================================================================

    async def render_plugin(
        self,
        plugin_id: str,
        request_data: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        渲染插件的通用 UI。

        通用的插件渲染入口，适用于各种插件类型。

        Args:
            plugin_id: 插件 ID
            request_data: 渲染请求数据
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 渲染结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "POST",
            f"/plugins/{plugin_id}/render",
            json=request_data,
            params=params,
        )

    async def send_plugin_event(
        self,
        plugin_id: str,
        request_data: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        向插件发送通用事件。

        通用的插件事件入口，适用于各种插件类型。

        Args:
            plugin_id: 插件 ID
            request_data: 事件数据
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 事件处理结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "POST",
            f"/plugins/{plugin_id}/event",
            json=request_data,
            params=params,
        )

    # =========================================================================
    # 5. MCP 工具执行
    # =========================================================================

    async def execute_tool(
        self,
        plugin_id: str,
        tool_name: str,
        request_data: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        执行插件的 MCP 工具。

        MCP (Model Context Protocol) 工具是插件暴露给 Agent 的
        可调用功能，用于执行各种操作。

        Args:
            plugin_id: 插件 ID
            tool_name: 工具名称
            request_data: 工具参数
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 工具执行结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "POST",
            f"/plugins/tools/execute/{plugin_id}/{tool_name}",
            json=request_data,
            params=params,
        )

    # =========================================================================
    # 6. 插件生命周期管理
    # =========================================================================

    async def list_installed_plugins(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        """
        获取所有已安装的插件列表。

        与 list_plugins 的区别：
        - list_plugins: 获取所有已注册的插件（包括未安装的）
        - list_installed_plugins: 仅获取已安装的插件

        Args:
            project_id: 项目 ID（可选，用于过滤）

        Returns:
            Dict[str, Any]: 包含 plugins 和 total 的响应
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request("GET", "/plugins/installed", params=params) or {"plugins": [], "total": 0}

    async def fetch_plugin_info(self, url: str) -> Optional[Dict[str, Any]]:
        """
        从 URL 获取插件信息。

        用于在安装前预览插件信息。

        Args:
            url: 插件仓库或包 URL

        Returns:
            Optional[Dict[str, Any]]: 插件元数据信息
        """
        return await self._request(
            "POST",
            "/plugins/fetch-info",
            json={"url": url},
        )

    async def install_plugin(self, request_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        从 YAML 配置安装插件。

        安装插件需要提供插件的 YAML 配置或包 URL。

        Args:
            request_data: 安装请求数据（包含插件配置）

        Returns:
            Optional[Dict[str, Any]]: 安装结果
        """
        return await self._request(
            "POST",
            "/plugins/install",
            json=request_data,
        )

    async def uninstall_plugin(self, plugin_id: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        卸载插件。

        Args:
            plugin_id: 要卸载的插件 ID
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 卸载结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "DELETE",
            f"/plugins/{plugin_id}/uninstall",
            params=params,
        )

    async def start_plugin(
        self,
        plugin_id: str,
        request_data: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        启动插件进程。

        插件运行在独立的进程中，此方法启动插件进程。

        Args:
            plugin_id: 插件 ID
            request_data: 启动参数
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 启动结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "POST",
            f"/plugins/{plugin_id}/start",
            json=request_data,
            params=params,
        )

    async def stop_plugin(self, plugin_id: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        停止插件进程。

        Args:
            plugin_id: 插件 ID
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 停止结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "POST",
            f"/plugins/{plugin_id}/stop",
            params=params,
        )

    async def restart_plugin(self, plugin_id: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        重启插件进程。

        Args:
            plugin_id: 插件 ID
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 重启结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "POST",
            f"/plugins/{plugin_id}/restart",
            params=params,
        )

    # =========================================================================
    # 7. 插件监控
    # =========================================================================

    async def get_plugin_logs(self, plugin_id: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        获取插件日志。

        Args:
            plugin_id: 插件 ID
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 日志内容
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "GET",
            f"/plugins/{plugin_id}/logs",
            params=params,
        )

    async def get_plugin_status(self, plugin_id: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        从运行时获取插件状态。

        状态包括：运行中、已停止、错误等。

        Args:
            plugin_id: 插件 ID
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 插件状态信息
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "GET",
            f"/plugins/{plugin_id}/status",
            params=params,
        )

    async def check_plugin_update(self, plugin_id: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        检查插件是否有更新。

        Args:
            plugin_id: 插件 ID
            project_id: 项目 ID（可选）

        Returns:
            Optional[Dict[str, Any]]: 更新检查结果
        """
        params = {"project_id": project_id} if project_id else None
        return await self._request(
            "GET",
            f"/plugins/{plugin_id}/check-update",
            params=params,
        )


# =============================================================================
# 全局单例实例
# =============================================================================

# 导出全局单例，供其他模块使用
plugin_runtime_client = PluginRuntimeClient()