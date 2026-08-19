"""MCP REST API endpoints for debugging and non-MCP clients.

The primary MCP Streamable HTTP endpoint is at ``POST /mcp/{device_id}``
(defined in ``main.py``). These REST endpoints provide a convenient
alternative for manual testing and debugging.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.services.mcp_server import mcp_proxy
from app.services.tcp_connection_manager import tcp_connection_manager

router = APIRouter()
logger = get_logger(__name__)


@router.get("/tools/{device_id}")
async def list_device_tools(device_id: str):
    """List available MCP tools from a specific device (REST helper).

    This fetches tools directly from the connected device via TCP RPC.
    """
    connection = tcp_connection_manager.get_connection(device_id)
    if not connection:
        raise HTTPException(
            status_code=404,
            detail=f"Device {device_id} is not connected",
        )

    result = await mcp_proxy.handle_list_tools(device_id)
    return result

'''
调用链是这样：

HTTP 请求先进入路由
app/api/v1/mcp.py 的 POST /tools/{device_id}/call 收到请求后，执行
app/api/v1/mcp.py -> mcp_proxy.handle_call_tool(device_id, params)

mcp_proxy 再转发到 TCP 连接对象
app/services/mcp_server.py 的 handle_call_tool 里执行
app/services/mcp_server.py -> connection.call_tool(name, arguments)

最后才是 TcpDeviceConnection.call_tool 发 JSON-RPC 到设备
app/services/tcp_connection_manager.py 里 call_tool 调用 send_request("tools/call", params, timeout)
本质是通过 TCP 发给设备端，不是回调 FastAPI 路由。
'''
@router.post("/tools/{device_id}/call")
async def call_device_tool(
    device_id: str,
    name: str,
    arguments: Dict[str, Any] = {},
):
    """Call a tool on a specific device (REST helper).

    This forwards the tool call directly to the connected device via TCP RPC.
    No name mapping or argument transformation is performed.
    """
    # 调用 call_device_tool 函数时，首先通过 tcp_connection_manager 获取指定 device_id 的连接对象。
    # 如果连接不存在，则返回 404 错误。然后，它调用 mcp_proxy 的 handle_call_tool 方法，将工具名称和参数转发给设备，并返回结果。
    connection = tcp_connection_manager.get_connection(device_id)
    if not connection:
        raise HTTPException(
            status_code=404,
            detail=f"Device {device_id} is not connected",
        )

    params = {"name": name, "arguments": arguments}
    result = await mcp_proxy.handle_call_tool(device_id, params)
    return result
