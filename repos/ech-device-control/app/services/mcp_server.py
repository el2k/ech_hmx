"""MCP Server - Pure transparent proxy for device tools.

This module implements the MCP Streamable HTTP protocol as a transparent
proxy to connected devices. It does NOT define any static tools, nor
perform any tool name mapping or argument transformation. All tool
definitions come from the devices themselves via TCP RPC ``tools/list``,
and all tool calls are forwarded as-is via ``tools/call``.

The ``device_id`` is resolved from the URL path (``/mcp/{device_id}``).
"""

from typing import Any, Dict, List, Optional

from app.config import settings
from app.core.logging import get_logger
from app.services.tcp_connection_manager import tcp_connection_manager

logger = get_logger("services.mcp_server")


class MCPProxy:
    """Transparent MCP proxy that forwards all requests to connected devices.
    透明MCP代理，将全部请求转发给已连接的设备。
    No static tool definitions, no name mapping, no argument transformation.
    没有静态工具定义、不做工具名称映射、不做参数转换。
    """

    # ------------------------------------------------------------------ #
    #  MCP protocol handlers        MCP协议各个方法处理器                  #
    # ------------------------------------------------------------------ #

    def handle_initialize(self) -> Dict[str, Any]:
        """Handle MCP ``initialize`` method.
        处理MCP初始化握手请求，返回本代理服务的能力描述。
        注意：这里不会返回tools列表，tools列表是动态从设备实时拉取。
        """
        return {
            "protocolVersion": "2024-11-05", # MCP协议版本
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": "tgo-device-control",
                "version": settings.SERVICE_VERSION,
            },
        }

    async def handle_list_tools(self, device_id: str) -> Dict[str, Any]:
        """Fetch tool list from device and return as‑is.
        从目标设备拉取工具列表，原样返回给MCP客户端。

        Args:
            device_id: Target device identifier. 目标设备ID

        Returns:
            ``{"tools": [...]}`` with raw tool definitions from the device.
            返回字典，tools数组是设备返回的原始工具定义
        """
        # 通过device_id拿到已经建立的TCP连接对象
        connection = tcp_connection_manager.get_connection(device_id)
        if not connection:
            logger.warning(f"list_tools: device {device_id} not connected")
            # 设备离线，返回空工具列表
            return {"tools": []}

        # 通过TCP RPC调用设备的 tools/list，获取设备本地的工具集合
        raw_tools = await connection.list_tools()
        return {"tools": raw_tools or []}

    async def handle_call_tool(
        self, device_id: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Forward tool call to device as‑is (no mapping, no transformation).
        将工具调用请求原样转发给设备，不修改工具名、不修改入参。

        Args:
            device_id: Target device identifier. 目标设备ID
            params: MCP ``tools/call`` params containing ``name`` and ``arguments``.
                    MCP协议tools/call的参数，包含工具name与arguments参数

        Returns:
            Raw tool call result from the device. 返回设备返回的原始执行结果
        """
        name: str = params.get("name", "")
        arguments: Dict[str, Any] = params.get("arguments", {})

        connection = tcp_connection_manager.get_connection(device_id)
        # 情况1：设备TCP连接不存在，直接返回MCP标准错误结构
        if not connection:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Error: Device {device_id} is not connected",
                    }
                ],
                "isError": True,
            }

        # 通过TCP RPC向真实设备下发工具调用
        result = await connection.call_tool(name, arguments)
        # 情况2：调用超时，返回错误
        if result is None:
            return {
                "content": [
                    {"type": "text", "text": "Error: Device request timed out"}
                ],
                "isError": True,
            }

        # Return result from device as‑is (already in MCP content format)
        # 直接透传设备返回结果，设备输出已经符合MCP content格式，无需二次封装
        return result

    # ------------------------------------------------------------------ #
    #  Unified JSON‑RPC dispatcher      JSON‑RPC统一请求分发器            #
    # ------------------------------------------------------------------ #

    async def handle_jsonrpc(
        self, device_id: str, body: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Dispatch a JSON‑RPC 2.0 request to the appropriate handler.
        JSON‑RPC请求总入口，根据method分发到上面各个处理函数

        Args:
            device_id: Target device identifier (from URL path).
                       目标设备ID，从HTTP URL路径 /mcp/{device_id}解析而来
            body: Parsed JSON‑RPC request body. 已经解析完毕的JSON‑RPC请求体

        Returns:
            JSON‑RPC response dict, or ``None`` for notifications.
            返回JSON‑RPC响应字典；通知类请求（无id）返回None，不需要回复
        """
        method: str = body.get("method", "")
        params: Dict[str, Any] = body.get("params", {})
        request_id = body.get("id")

        # Notifications (no ``id``) – acknowledge silently
        # JSON‑RPC通知：没有id字段，不需要返回任何响应，直接返回None
        if request_id is None:
            return None

        result: Dict[str, Any]

        # 根据MCP method分发
        if method == "initialize":
            result = self.handle_initialize()
        elif method == "tools/list":
            result = await self.handle_list_tools(device_id)
        elif method == "tools/call":
            result = await self.handle_call_tool(device_id, params)
        elif method == "ping":
            result = {}
        else:
            # JSON‑RPC标准错误：方法不存在 -32601
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            }

        # 包装成标准JSON‑RPC成功响应返回
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }


# Global singleton 全局单例，FastAPI路由直接使用该实例
mcp_proxy = MCPProxy()