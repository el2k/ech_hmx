"""TCP 连接管理器服务。
这个模块用于管理与 Peekaboo 设备的 TCP 连接，提供方法来发送请求和调用已连接设备上的工具。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from app.config import settings
from app.core.logging import get_logger

logger = get_logger("services.tcp_connection_manager")

@dataclass
class TcpDeviceConnection:
    """Represents an active TCP connection from a Peekaboo device."""
    # 代表一个来自 Peekaboo 设备的活动 TCP 连接。它包含设备的标识信息、连接状态、工具列表以及用于发送请求和处理响应的方法。
    agent_id: str  # Also serves as device_id (UUID)
    name: str
    version: str
    capabilities: List[str]
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    tools: List[Dict[str, Any]] = field(default_factory=list)
    project_id: Optional[str] = None  # Associated project ID
    device_db_id: Optional[str] = None  # Database device ID (same as agent_id for new auth)
    _request_id: int = 0
    _pending_requests: Dict[Union[int, str], asyncio.Future[Any]] = field(
        default_factory=dict
    )
    # next_request_id 指定一个方法，用于生成下一个唯一的请求 ID。每次发送请求时，都会调用此方法来获取一个新的请求 ID，以便在处理响应时能够正确匹配请求和响应。
    def next_request_id(self) -> int:
        """Generate the next request ID."""
        self._request_id += 1
        return self._request_id
    # send_message 指定一个异步方法，用于向设备发送 JSON 消息。它将消息序列化为 JSON 字符串，并通过 TCP 连接的 writer 发送给设备。
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Send a JSON message to the device.

        Args:
            message: JSON-serializable message to send.
        """
        data = (json.dumps(message) + "\n").encode("utf-8")
        self.writer.write(data)
        # drain() 方法用于确保所有数据都已被写入底层传输缓冲区，并等待直到写入完成。它是 asyncio 中的一个异步方法，
        # 用于处理流式写入操作，确保数据发送的可靠性。
        await self.writer.drain()
    # send_request 指定一个异步方法，用于向设备发送 JSON-RPC 请求并等待响应。它生成一个唯一的请求 ID，将请求发送给设备，并在指定的超时时间内等待响应。如果超时或发生错误，它会记录日志并返回 None。
    async def send_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Send a JSON-RPC request and wait for response.

        Args:
            method: RPC method name.
            params: Optional method parameters.
            timeout: Optional timeout in seconds.

        Returns:
            Response result or None on timeout/error.
        """
        timeout = timeout or settings.TCP_RPC_TIMEOUT
        request_id = self.next_request_id()

        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        '''
        发送时：你把 future 和 request_id 绑在一起存进了字典。
        发送时：你把 request_id 塞进了网络请求里发给对方。
        接收时：对方把 request_id 原封不动地还回来。
        接收时：你的代码用还回来的 request_id，去字典里精准地找到了那个 future，并给它赋值。
        如果没有这个 request_id 和字典的配合，future 就会变成一个永远等不到结果的死锁。
        这就是 JSON-RPC 这类异步通信协议的精髓：通过 ID 来匹配请求和响应。'''
        # 在这段代码里，future 就是一个跨时间的通信桥梁。它让发送请求的协程可以优雅地“睡一觉”，等后台真正收到响应数据时，再由另一个协程把它“叫醒”并递上结果。
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        # _pending_requests 字典用于存储当前所有待处理的请求。每个请求都使用唯一的请求 ID 作为键，将对应的 asyncio.Future 对象作为值存储在字典中。
        self._pending_requests[request_id] = future

        try:
            # await self.send_message(request) 仅仅保证了信件已经成功投递到邮筒（网络通道）里。
            await self.send_message(request)
            # wait_for() 方法用于等待一个异步操作完成，并在指定的超时时间内返回结果。如果在超时时间内没有收到响应，它会引发 asyncio.TimeoutError 异常。
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.error(
                f"TCP request timeout: agent={self.agent_id}, method={method}"
            )
            return None
        except Exception as e:
            logger.error(
                f"TCP request error: agent={self.agent_id}, method={method}: {e}"
            )
            return None
        finally:
            self._pending_requests.pop(request_id, None)
    # call_tool 指定一个异步方法，用于调用设备上的工具。它使用 tools/call 方法发送请求，并返回工具调用的结果。如果超时或发生错误，它会返回 None。
    async def call_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Call a tool on the device using tools/call method.

        Args:
            name: Tool name to call.
            arguments: Tool arguments.
            timeout: Optional timeout in seconds.

        Returns:
            Tool call result or None on timeout/error.
        """
        params = {"name": name, "arguments": arguments or {}}
        return await self.send_request("tools/call", params, timeout)
    # list_tools 指定一个异步方法，用于获取设备上可用工具的列表。它使用 tools/list 方法发送请求，并返回工具定义的列表。如果超时或发生错误，它会返回 None。
    async def list_tools(
        self, timeout: Optional[int] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Get list of available tools from the device.

        Args:
            timeout: Optional timeout in seconds.

        Returns:
            List of tool definitions or None on error.
        """
        result = await self.send_request("tools/list", {}, timeout)
        if result and "tools" in result:
            self.tools = result["tools"]
            return result["tools"]
        return None
    # ping 指定一个异步方法，用于向设备发送 ping 请求以检查连接是否仍然有效。它使用 ping 方法发送请求，并返回 True 表示收到 pong 响应，返回 False 表示未收到响应或发生错误。
    async def ping(self, timeout: Optional[int] = None) -> bool:
        """Send a ping request to check connection.

        Args:
            timeout: Optional timeout in seconds.

        Returns:
            True if pong received, False otherwise.
        """
        result = await self.send_request("ping", {}, timeout or 10)
        return result is not None and result.get("pong", False)
    # handle_response 指定一个方法，用于处理从设备收到的 JSON-RPC 响应。它根据响应中的请求 ID 查找对应的 asyncio.Future 对象，
    # 并将结果或错误设置到该 Future 中，从而唤醒等待该请求的协程。
    def handle_response(self, message: Dict[str, Any]) -> None:
        """Handle a JSON-RPC response from the device.

        Args:
            message: Response message with id, result/error.
        """
        request_id = message.get("id")
        if request_id is None:
            return

        future = self._pending_requests.get(request_id)
        if future and not future.done():
            if "error" in message:
                error = message["error"]
                logger.warning(f"TCP device error response: {error}")
                future.set_result({"error": error})
            else:
                future.set_result(message.get("result"))

class TcpConnectionManager:
    """
    单例管理器，用于管理 TCP 设备连接。
    管理来自 Peekaboo 代理的活动 TCP 连接，提供设备查找和连接生命周期管理。
    业务背景：后端服务与远端Agent设备之间通过原始TCP长链接通信；该类统一管理所有设备长连接，
    实现注册、注销、心跳保活、超时断开，全局只存在一个管理器实例。
    """

    # 单例静态实例，保存全局唯一对象
    _instance: Optional["TcpConnectionManager"] = None

    def __new__(cls) -> "TcpConnectionManager":
        """
        __new__ 控制对象实例化，实现单例模式
        每次创建 TcpConnectionManager() 都返回同一个对象
        """
        if cls._instance is None:
            # 首次实例化：创建底层对象
            cls._instance = super().__new__(cls)
            # 标记是否已经完成初始化，避免 __init__ 重复执行
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        """
        构造初始化；因为单例会多次调用 __init__，靠 _initialized 屏障只执行一次
        """
        if self._initialized:
            return  # 已经初始化过，直接跳过，防止重复覆盖成员变量
        self._initialized = True

        # 存储所有在线TCP设备连接；key：agent_id(设备唯一id)，value：TcpDeviceConnection连接对象
        self._connections: Dict[str, TcpDeviceConnection] = {}
        # 异步锁：多协程同时增删 _connections 字典，防止并发竞争、数据错乱
        self._lock = asyncio.Lock()
        # 后台心跳循环任务对象
        self._heartbeat_task: Optional[asyncio.Task[None]] = None
        logger.info("TcpConnectionManager initialized")

    async def initialize(self) -> None:
        """初始化管理器，启动后台心跳监控协程，服务启动时调用一次"""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("TcpConnectionManager heartbeat monitor started")

    async def shutdown(self) -> None:
        """
        服务优雅关闭：停止心跳任务，逐个关闭全部设备TCP连接
        服务退出、重启时调用，做资源回收
        """
        if self._heartbeat_task:
            # 取消心跳后台任务
            self._heartbeat_task.cancel()
            try:
                # 等待任务真正结束，捕获取消异常
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # list()拷贝keys，避免遍历同时字典被修改；逐个注销所有设备连接
        for agent_id in list(self._connections.keys()):
            await self.unregister_connection(agent_id)

        logger.info("TcpConnectionManager shutdown complete")

    async def register_connection(
        self,
        agent_id: str,
        name: str,
        version: str,
        capabilities: List[str],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        project_id: Optional[str] = None,
        device_db_id: Optional[str] = None,
    ) -> TcpDeviceConnection:
        """
        注册新的TCP设备连接，设备代理连上服务端TCP端口时调用该方法
        如果该agent_id已经存在旧连接，会主动关闭旧连接，防止设备重复登录
        Args:
            agent_id: 设备/agent唯一标识UUID
            name: 设备显示名称
            version: 客户端代理版本号
            capabilities: 设备支持的能力集合
            reader: asyncio TCP读流对象
            writer: asyncio TCP写流对象
            project_id: 归属项目ID
            device_db_id: 数据库中设备记录ID
        Returns:
            返回封装好的连接对象 TcpDeviceConnection
        """
        # 构造设备连接实例，把socket读写流、元信息全部封装进去
        connection = TcpDeviceConnection(
            agent_id=agent_id,
            name=name,
            version=version,
            capabilities=capabilities,
            reader=reader,
            writer=writer,
            project_id=project_id,
            device_db_id=device_db_id,
        )

        # 加异步锁，并发场景下安全修改连接字典
        async with self._lock:
            # 同一个设备重复上线：关闭旧的TCP连接
            if agent_id in self._connections:
                old_conn = self._connections[agent_id]
                try:
                    old_conn.writer.close()
                    await old_conn.writer.wait_closed()
                except Exception:
                    # 旧连接本身已经断开，忽略异常
                    pass
            # 将新连接存入内存字典
            self._connections[agent_id] = connection

        logger.info(f"TCP device registered: {name} ({agent_id})")
        return connection

    async def unregister_connection(self, agent_id: str) -> None:
        """
        注销连接：设备下线、心跳超时、服务关闭时调用
        1.从内存字典移除连接
        2.取消该连接上所有挂起未完成请求future
        3.关闭底层TCP socket流
        Args:
            agent_id: 需要下线的设备id
        """
        async with self._lock:
            # pop取出，不存在返回None
            connection = self._connections.pop(agent_id, None)

        if connection:
            logger.info(
                f"TCP device unregistered: {connection.name} ({agent_id})"
            )
            # 把该设备还没返回的请求全部cancel，释放协程future，防止内存泄漏
            for future in connection._pending_requests.values():
                if not future.done():
                    future.cancel()

            try:
                # 关闭socket写流，等待关闭完成
                connection.writer.close()
                await connection.writer.wait_closed()
            except Exception:
                # 连接已经断开，吞掉异常
                pass

    def get_connection(self, agent_id: str) -> Optional[TcpDeviceConnection]:
        """根据agent_id获取在线设备连接；同步方法，只读不加锁"""
        return self._connections.get(agent_id)

    def list_connections(self) -> List[TcpDeviceConnection]:
        """获取全部在线设备连接列表"""
        return list(self._connections.values())

    def get_connected_count(self) -> int:
        """获取当前在线设备数量"""
        return len(self._connections)

    def update_heartbeat(self, agent_id: str) -> None:
        """
        收到设备上报心跳包时调用，更新该设备最后活跃时间戳 last_seen
        心跳循环会拿这个时间戳判断是否超时离线
        """
        connection = self._connections.get(agent_id)
        if connection:
            connection.last_seen = datetime.utcnow()

    async def _heartbeat_loop(self) -> None:
        """
        后台常驻协程任务，心跳保活主循环
        每隔 HEARTBEAT_INTERVAL 执行一轮：
        1.遍历全部在线设备
        2.判断距离last_seen是否超过超时阈值
        3.主动发送ping(jsonrpc ping消息)探测设备存活
        4.ping失败 / 超时，就把设备执行unregister踢下线
        """
        while True:
            try:
                await asyncio.sleep(settings.HEARTBEAT_INTERVAL)

                now = datetime.utcnow()
                timeout = settings.HEARTBEAT_TIMEOUT
                disconnected: List[str] = []

                # list拷贝items，避免遍历中字典被修改
                for agent_id, connection in list(self._connections.items()):
                    elapsed = (now - connection.last_seen).total_seconds()
                    # 超过心跳超时时间，标记断开
                    if elapsed > timeout:
                        logger.warning(
                            f"TCP device heartbeat timeout: "
                            f"{connection.name} ({agent_id})"
                        )
                        disconnected.append(agent_id)
                    else:
                        # 向设备发送ping探测报文 jsonrpc 2.0协议
                        try:
                            await connection.send_message(
                                {"jsonrpc": "2.0", "method": "ping", "params": {}}
                            )
                        except Exception as e:
                            # ping发送失败，网络断了，标记离线
                            logger.warning(
                                f"Failed to ping TCP device {agent_id}: {e}"
                            )
                            disconnected.append(agent_id)

                # 批量处理断开的设备，执行下线注销
                for agent_id in disconnected:
                    await self.unregister_connection(agent_id)

            except asyncio.CancelledError:
                # 任务被cancel，正常退出循环
                break
            except Exception as e:
                # 心跳循环内部异常不能崩溃整个后台任务，打印错误继续下一轮循环
                logger.error(f"TCP heartbeat loop error: {e}")


# 全局唯一单例实例，项目其他模块直接 import 使用 tcp_connection_manager
tcp_connection_manager = TcpConnectionManager()