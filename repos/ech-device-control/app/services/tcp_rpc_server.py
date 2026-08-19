"""
TCP JSON-RPC 服务为了 Peekaboo 设备连接。
这个模块实现了一个 TCP 服务器，它接受来自 Peekaboo 设备的连接，使用 JSON-RPC 2.0 协议。
协议：
- 消息是以换行符分隔的 JSON
- 第一个消息必须是带有 bindCode 或 deviceToken 的 'auth' 请求
- 认证后，服务器将工具/调用请求转发到设备
认证：
- 第一次注册：使用 bindCode（从 Web UI 获取）
- 重新连接：使用 deviceToken（从第一次注册获取）
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.device import DeviceStatus
from app.schemas.tcp_rpc import JsonRpcErrorCode
from app.services.bind_code_service import bind_code_service
from app.services.device_service import DeviceService
from app.services.tcp_connection_manager import tcp_connection_manager

if TYPE_CHECKING:
    from app.services.tcp_connection_manager import TcpDeviceConnection

logger = get_logger("services.tcp_rpc_server")

class TcpRpcServer:
    """TCP JSON‑RPC Server for Peekaboo protocol.

    Listens for TCP connections from Peekaboo devices and handles
    the JSON‑RPC 2.0 protocol for device control.

    Authentication is performed using bind codes (first‑time registration)
    or device tokens (reconnection).
    """
    '''
    完整设备 TCP 连接流程
    后端启动，tcp_rpc_server.start()，监听 TCP 端口。
    客户端设备建立 TCP 连接。
    第一条报文必须是auth
    场景 A：bindCode → _authenticate调用DeviceService.register_device，数据库新建设备，下发deviceToken。
    场景 B：deviceToken → 查询数据库设备，标记 ONLINE，重连成功。
    认证成功，tcp_connection_manager.register_connection保存这条连接。
    启动_message_reader_loop后台任务持续读设备报文。
    后端主动调用connection.list_tools()向设备发 RPC 请求，询问设备具备哪些工具。
    后续双向通信：
    后端主动下发 RPC 调用指令（调用设备本地工具）。
    设备上送 ping/heartbeat；设备返回 RPC 结果。
    连接断开：finally块执行，数据库设备置 OFFLINE，全局连接管理器注销连接。'''
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9876,
    ) -> None:
        """Initialize the TCP RPC server.

        Args:
            host: Host address to bind to.
            port: Port number to listen on.
        """
        self.host = host
        self.port = port
        self.server: Optional[asyncio.AbstractServer] = None
        # asyncio服务实例
        self._serving_task: Optional[asyncio.Task[None]] = None
        # 后台运行serve_forever的task，方便stop时cancel

    async def start(self) -> None:
        """Start the TCP server. 启动TCP服务，后台持续监听"""
        logger.info(f"[DEBUG] Starting TCP RPC Server on {self.host}:{self.port}...")
        try:
            # 创建TCP服务，每一个新连接回调 _handle_connection
            # 只是创建、绑定、监听 socket，并不会阻塞，也不会开始循环接收客户端连接。
            self.server = await asyncio.start_server(
                self._handle_connection, self.host, self.port
            )
            addr = self.server.sockets[0].getsockname()
            logger.info(f"TCP RPC Server listening on {addr[0]}:{addr[1]}")
            logger.info(f"[DEBUG] TCP Server socket info: {self.server.sockets}")
            logger.info(f"[DEBUG] TCP Server is_serving: {self.server.is_serving()}")

            # serve_forever 会阻塞，放到后台task运行，不阻塞主程序
            # 这是一个无限循环协程，内部不停调用 accept()，等待新 TCP 客户端进来；
            # 一旦有新连接，就调用你传入的 _handle_connection(reader,writer)。
            self._serving_task = asyncio.create_task(self.server.serve_forever())
            logger.info("[DEBUG] TCP Server serve_forever task started")
        except Exception as e:
            logger.error(f"[DEBUG] Failed to start TCP RPC Server: {e}", exc_info=True)

    async def stop(self) -> None:
        """Stop the TCP server. 优雅关闭服务"""
        if self.server:
            self.server.close()        # 停止接收新连接
            await self.server.wait_closed()
            logger.info("TCP RPC Server stopped")

        # 取消后台监听任务
        if self._serving_task:
            self._serving_task.cancel()
            try:
                await self._serving_task
            except asyncio.CancelledError:
                pass

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a new TCP connection.
        每一条客户端TCP连接，都会跑这个函数；reader读数据，writer写数据

        Args:
            reader: Async stream reader.
            writer: Async stream writer.
        """
        addr = writer.get_extra_info("peername") # 客户端IP端口
        socket_info = writer.get_extra_info("socket")
        logger.info(f"[DEBUG] New TCP connection from {addr}")
        logger.info(f"[DEBUG] Socket info: {socket_info}")
        logger.info(f"[DEBUG] Connection extra info - sockname: {writer.get_extra_info('sockname')}")

        device_id: Optional[str] = None

        try:
            # ========== 步骤1：第一条消息必须是 auth 认证 ==========
            logger.info(f"[DEBUG] Waiting for auth message from {addr}...")
            message = await self._read_message(reader)
            logger.info(f"[DEBUG] Received message from {addr}: {message}")
            if message is None:
                logger.warning(f"[DEBUG] No message received from {addr}, connection may have closed")
                return

            # 协议强制：连接上来第一条RPC方法必须是auth
            if message.get("method") != "auth":
                logger.warning(f"[DEBUG] First message from {addr} must be 'auth', got: {message.get('method')}")
                await self._send_error(
                    writer,
                    message.get("id"),
                    JsonRpcErrorCode.INVALID_REQUEST,
                    "First message must be 'auth'",
                )
                return

            # ========== 步骤2：认证逻辑 bindCode / deviceToken ==========
            params = message.get("params", {})
            logger.info(f"[DEBUG] Auth params from {addr}: bindCode={params.get('bindCode')}, hasDeviceToken={bool(params.get('deviceToken'))}")
            # _authenticate返回None表示认证失败，返回元组表示认证成功
            auth_result = await self._authenticate(params, addr)

            if auth_result is None:
                # 认证失败，_authenticate内部已经打日志，返回RPC错误给客户端
                logger.warning(f"[DEBUG] Authentication failed for {addr}")
                await self._send_error(
                    writer,
                    message.get("id"),
                    JsonRpcErrorCode.AUTH_FAILED,
                    "Authentication failed: invalid bind code or device token",
                )
                return

            # 认证成功解包：设备id、token、项目id、设备名称、版本、是否新注册
            device_id, device_token, project_id, device_name, device_version, is_new_registration = auth_result
            logger.info(f"[DEBUG] Auth successful: device_id={device_id}, project_id={project_id}, is_new={is_new_registration}")

            # 在全局连接管理器注册这条长连接，保存reader/writer，后续上层业务可以通过device_id找到这个TCP连接
            connection = await tcp_connection_manager.register_connection(
                agent_id=device_id,
                name=device_name,
                version=device_version,
                capabilities=["tools/call", "tools/list", "ping"],  # 声明设备支持的RPC方法
                reader=reader,
                writer=writer,
                project_id=project_id,
                device_db_id=device_id,
            )

            # 组装认证成功返回报文
            response_data: Dict[str, Any] = {
                "status": "ok",
                "deviceId": device_id,
                "projectId": project_id,
            }

            # 如果是首次注册，把生成的deviceToken下发给客户端；重连不返回token
            if is_new_registration and device_token:
                response_data["deviceToken"] = device_token
                response_data["message"] = "Device registered successfully"
            else:
                response_data["message"] = "Reconnected successfully"

            await self._send_response(writer, message.get("id"), response_data)

            logger.info(
                f"TCP device authenticated: {device_name} v{device_version} ({device_id})"
                f" [{'new' if is_new_registration else 'reconnected'}]"
            )

            # ========== 步骤3：启动后台消息循环任务 ==========
            # 关键点：必须单独开task跑消息循环；因为后端会主动向设备发请求（list_tools），需要同时接收设备返回的response
            reader_task = asyncio.create_task(
                self._message_reader_loop(reader, writer, connection, device_id)
            )

            # ========== 步骤4：认证完成后主动询问设备支持哪些工具 ==========
            try:
                tools = await connection.list_tools(timeout=30)
                if tools:
                    logger.info(f"Device {device_id} supports {len(tools)} tools")
            except Exception as e:
                logger.warning(f"Failed to fetch tools list for device {device_id}: {e}")

            # ========== 步骤5：等待消息循环结束（连接断开时这里返回） ==========
            await reader_task

        except ConnectionError as e:
            logger.info(f"[DEBUG] TCP connection closed by {addr}: {e}")
        except json.JSONDecodeError as e:
            logger.warning(f"[DEBUG] Invalid JSON from {addr}: {e}")
        except Exception as e:
            logger.error(f"[DEBUG] Error handling TCP connection from {addr}: {e}", exc_info=True)
        finally:
            # 连接无论正常/异常断开，都执行清理
            logger.info(f"[DEBUG] Connection cleanup for {addr}, device_id={device_id}")
            if device_id:
                # 更新数据库设备状态为离线
                await self._update_device_offline(device_id)
                # 全局连接管理器移除该设备连接
                await tcp_connection_manager.unregister_connection(device_id)
            else:
                # 还没认证成功，直接关闭socket
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception as close_error:
                    logger.warning(f"[DEBUG] Error closing writer for {addr}: {close_error}")

    async def _message_reader_loop(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        connection: TcpDeviceConnection,
        device_id: str,
    ) -> None:
        """Background task to read and process messages from the device.
        后台循环：持续读取设备发来JSON‑RPC报文
        并发模型：后端主动发请求给设备，设备返回的response在这里接收；同时设备主动上送ping/heartbeat

        Args:
            reader: Async stream reader.
            writer: Async stream writer.
            connection: TcpDeviceConnection instance.
            device_id: Device ID for logging and heartbeat updates.
        """
        while True:
            try:
                msg = await self._read_message(reader)
                if msg is None:
                    # read拿到空，代表对端关闭连接，退出循环
                    break

                # 任何收到设备消息，都更新该连接心跳，不需要只依赖专门heartbeat报文
                tcp_connection_manager.update_heartbeat(device_id)

                # ---情况1：这是后端主动调用设备后，设备返回的响应报文（含result/error）
                # 交给connection内部的pending请求映射，唤醒等待的协程返回结果
                if "result" in msg or "error" in msg:
                    connection.handle_response(msg)
                    continue

                # ---情况2：设备主动发来的请求/通知
                method = msg.get("method")
                msg_id = msg.get("id")

                if method == "ping":
                    # 设备ping，后端回复pong
                    if msg_id is not None:
                        await self._send_response(
                            writer,
                            msg_id,
                            {"pong": True, "timestamp": int(asyncio.get_event_loop().time())},
                        )

                elif method == "pong":
                    # 设备回复pong通知，心跳已经上面更新，无需额外处理
                    pass

                elif method == "heartbeat":
                    # 设备心跳报文
                    if msg_id is not None:
                        await self._send_response(writer, msg_id, {"status": "ok"})

                else:
                    logger.debug(
                        f"Received message from TCP device {device_id}: {method}"
                    )
            except Exception as e:
                logger.warning(f"Error in message reader loop for {device_id}: {e}")
                break

    async def _authenticate(
        self,
        params: Dict[str, Any],
        addr: Any,
    ) -> Optional[Tuple[str, Optional[str], str, str, str, bool]]:
        """Authenticate a device using bind code or device token.
        设备认证核心逻辑
        bindCode：首次绑定，调用DeviceService.register_device创建数据库设备记录
        deviceToken：断线重连，查询已有设备，标记online

        Returns:
            Tuple of (device_id, device_token, project_id, device_name, device_version, is_new_registration)
            or None if authentication failed.
        """
        bind_code = params.get("bindCode")
        device_token = params.get("deviceToken")
        device_info = params.get("deviceInfo", {})

        device_name = device_info.get("name", "Unknown Device")
        device_version = device_info.get("version", "unknown")

        logger.info(f"[DEBUG] _authenticate called from {addr}")
        logger.info(f"[DEBUG] bind_code={bind_code}, has_device_token={bool(device_token)}")
        logger.info(f"[DEBUG] device_info={device_info}")

        # 两个凭证都没有，直接认证失败
        if not bind_code and not device_token:
            logger.warning(f"[DEBUG] Auth from {addr}: neither bindCode nor deviceToken provided")
            return None

        try:
            # 认证内部新建独立数据库会话
            async with AsyncSessionLocal() as db:
                logger.info(f"[DEBUG] Database session created for auth from {addr}")
                device_service = DeviceService(db)

                if bind_code:
                    # ========== 首次注册绑定 ==========
                    logger.info(f"[DEBUG] Processing bind_code registration from {addr}")
                    os_name = device_info.get("os")
                    if not os_name:
                        logger.warning(f"[DEBUG] Auth from {addr}: OS is required for first‑time registration")
                        return None

                    logger.info(f"[DEBUG] Calling device_service.register_device with bind_code={bind_code}")
                    device = await device_service.register_device(
                        bind_code=bind_code,
                        device_name=device_name,
                        device_type="desktop",
                        os=os_name,
                        os_version=device_info.get("osVersion"),
                        screen_resolution=device_info.get("screenResolution"),
                    )

                    if not device:
                        logger.warning(f"[DEBUG] Auth from {addr}: invalid or expired bind code '{bind_code}'")
                        return None

                    logger.info(f"[DEBUG] Device registered: {device_name} ({device.id}) for project {device.project_id}")
                    return (
                        str(device.id),
                        device.device_token,
                        str(device.project_id),
                        device_name,
                        device_version,
                        True,  # is_new_registration
                    )

                elif device_token:
                    # ========== 使用token重连 ==========
                    logger.info(f"[DEBUG] Processing device_token reconnection from {addr}")
                    device = await device_service.get_device_by_token(device_token)

                    if not device:
                        logger.warning(f"[DEBUG] Auth from {addr}: invalid device token")
                        return None

                    # 更新数据库状态为在线
                    await device_service.update_device_status(device.id, DeviceStatus.ONLINE)

                    logger.info(f"[DEBUG] Device reconnected: {device.device_name} ({device.id})")
                    return (
                        str(device.id),
                        None,  # 重连不回传token
                        str(device.project_id),
                        device.device_name,
                        device_version,
                        False,  # is_new_registration
                    )
        except Exception as e:
            logger.error(f"[DEBUG] Exception in _authenticate from {addr}: {e}", exc_info=True)
            return None

        return None

    async def _update_device_offline(self, device_id: str) -> None:
        """Update device status to offline when connection closes.
        TCP连接断开，把数据库设备改为离线
        """
        try:
            import uuid as uuid_module
            async with AsyncSessionLocal() as db:
                device_service = DeviceService(db)
                await device_service.update_device_status(
                    uuid_module.UUID(device_id),
                    DeviceStatus.OFFLINE,
                )
                logger.debug(f"Device {device_id} status updated to offline")
        except Exception as e:
            logger.warning(f"Failed to update device {device_id} status to offline: {e}")

    async def _read_message(
        self, reader: asyncio.StreamReader
    ) -> Optional[Dict[str, Any]]:
        """Read a single JSON‑RPC message from the stream.
        帧协议：按行读取，`readline()`，每条JSON报文以`\n`换行结尾
        """
        try:
            logger.debug("[DEBUG] _read_message: waiting for readline...")
            line = await reader.readline()
            if not line:
                logger.debug("[DEBUG] _read_message: received empty line (connection closed)")
                return None
            decoded = line.decode("utf‑8").strip()
            logger.debug(f"[DEBUG] _read_message: received raw data ({len(line)} bytes): {decoded[:200]}...")
            result = json.loads(decoded)
            logger.debug(f"[DEBUG] _read_message: parsed JSON successfully")
            return result
        except json.JSONDecodeError as e:
            logger.warning(f"[DEBUG] _read_message: JSON decode error: {e}")
            raise
        except Exception as e:
            logger.warning(f"[DEBUG] _read_message: unexpected error: {e}")
            return None

    async def _send_message(
        self, writer: asyncio.StreamWriter, message: Dict[str, Any]
    ) -> None:
        """Send a JSON‑RPC message.
        发送报文：json序列化 + 追加换行符，drain确保缓冲区发送出去
        """
        data = (json.dumps(message) + "\n").encode("utf‑8")
        writer.write(data)
        await writer.drain()

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        msg_id: Any,
        result: Any,
    ) -> None:
        """Send a JSON‑RPC success response. 成功返回报文"""
        response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
        await self._send_message(writer, response)

    async def _send_error(
        self,
        writer: asyncio.StreamWriter,
        msg_id: Any,
        code: int,
        message: str,
        data: Optional[Any] = None,
    ) -> None:
        """Send a JSON‑RPC error response. 返回错误报文"""
        error: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        response = {"jsonrpc": "2.0", "id": msg_id, "error": error}
        await self._send_message(writer, response)


# 全局单例，项目启动时调用tcp_rpc_server.start()
tcp_rpc_server = TcpRpcServer(
    host=settings.TCP_RPC_HOST,
    port=settings.TCP_RPC_PORT,
)
