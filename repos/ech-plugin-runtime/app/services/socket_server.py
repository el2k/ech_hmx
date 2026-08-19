"""Plugin Socket Server - Unix Socket / TCP server for plugin communication."""

from __future__ import annotations

import asyncio
import json
import os
import struct
from typing import Optional

from app.config import settings
from app.core.logging import get_logger
from app.services.plugin_manager import plugin_manager, PluginConnection

logger = get_logger("services.socket_server")

# Global state
_unix_server: Optional[asyncio.AbstractServer] = None
_tcp_server: Optional[asyncio.AbstractServer] = None
_server_tasks: List[asyncio.Task] = []

async def _recv_message(reader: asyncio.StreamReader) -> Optional[dict]:
    """Receive a length-prefixed JSON message."""
    # 接收消息的函数，首先读取4字节的长度前缀，然后读取指定长度的JSON数据并解析为字典。
    try:
        # Read 4-byte length prefix (big-endian)
        length_bytes = await reader.readexactly(4)
        length = struct.unpack(">I", length_bytes)[0]
        
        # Read JSON data
        json_bytes = await reader.readexactly(length)
        return json.loads(json_bytes.decode("utf-8"))
    except asyncio.IncompleteReadError:
        return None
    except Exception as e:
        logger.error(f"Error receiving message: {e}")
        return None

# 发送消息的函数，将字典序列化为JSON字节流，计算长度并添加长度前缀，然后写入流并刷新。
async def _send_message(writer: asyncio.StreamWriter, message: dict):
    """Send a length-prefixed JSON message."""
    json_bytes = json.dumps(message, ensure_ascii=False).encode("utf-8")
    length_prefix = struct.pack(">I", len(json_bytes))
    writer.write(length_prefix + json_bytes)
    # drain()方法确保所有数据都被发送出去，避免缓冲区阻塞。
    await writer.drain()

# 处理单个插件连接的函数，首先接收注册消息，验证其合法性，然后注册插件并进入主消息循环。
async def _handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single plugin connection."""
    plugin_id: Optional[str] = None
    plugin: Optional[PluginConnection] = None
    peer = writer.get_extra_info("peername") or "unknown"
    
    logger.info(f"New plugin connection from {peer}")
    
    try:
        # First message must be a 'register' request
        # 接收插件的第一个消息，必须是注册请求，如果不是，则发送错误响应并返回。
        first_msg = await asyncio.wait_for(_recv_message(reader), timeout=30)
        if not first_msg or first_msg.get("method") != "register":
            logger.warning(f"Invalid first message from {peer}, expected 'register'")
            await _send_message(writer, {
                "jsonrpc": "2.0",
                "id": first_msg.get("id") if first_msg else None,
                "error": {"code": -32600, "message": "First message must be 'register'"}
            })
            return
        
        # Extract registration info
        # 从注册消息中提取插件的相关信息，包括ID、名称、版本、功能列表、描述、作者和开发者令牌。
        params = first_msg.get("params", {})
        pid = params.get("id")
        name = params.get("name", "unknown")
        version = params.get("version", "0.0.0")
        capabilities = params.get("capabilities", [])
        description = params.get("description")
        author = params.get("author")
        dev_token = params.get("dev_token")
        
        # Register the plugin
        # Check if it's a TCP connection (for dev mode verification)
        # For TCP, peer is a tuple (host, port); for UNIX, it's a string (path)
        is_tcp = isinstance(peer, tuple)
        
        try:
            plugin_id, plugin = await plugin_manager.register(
                plugin_id=pid,
                name=name,
                version=version,
                capabilities=capabilities,
                reader=reader,
                writer=writer,
                description=description,
                author=author,
                dev_token=dev_token,
                is_tcp=is_tcp,
            )
        except ValueError as e:
            logger.warning(f"Registration failed for {peer}: {e}")
            await _send_message(writer, {
                "jsonrpc": "2.0",
                "id": first_msg.get("id"),
                "error": {"code": -32000, "message": str(e)}
            })
            return
        
        # Send success response
        await _send_message(writer, {
            "jsonrpc": "2.0",
            "id": first_msg.get("id"),
            "result": {
                "success": True,
                "plugin_id": plugin_id,
                "host_version": settings.SERVICE_VERSION,
            }
        })
        
        logger.info(f"Plugin {name} v{version} registered as {plugin_id}")
        
        # Main message loop
        # 进入主消息循环，持续接收插件发送的消息，如果是响应消息则交给插件管理器处理，否则记录警告日志。
        while True:
            '''
            协程 A 发送请求，创建一个 future，然后 await future 挂起。
            插件 处理请求，返回 JSON-RPC 响应。
            当前方法 (handle_response) 收到响应，找到对应的 future，调用 set_result 把数据塞进去。
            协程 A 被唤醒，拿到数据，继续执行。
            所以，插件只是数据的生产者，而这个 future 是专门为了通知消费者（等待中的协程）而存在的。'''
            # message 接收插件发送的消息，如果消息为 None，表示插件断开连接，跳出循环。
            message = await _recv_message(reader)
            if message is None:
                logger.info(f"Plugin {plugin_id} disconnected")
                break
            
            # Handle response (from our requests to the plugin)
            # 处理响应消息，如果消息中包含"result"或"error"字段，则调用插件管理器的handle_response方法处理，否则记录警告日志。
            if "result" in message or "error" in message:
                await plugin_manager.handle_response(plugin, message)
            else:
                # This shouldn't happen in normal flow - plugins only respond
                logger.warning(f"Unexpected message from plugin {plugin_id}: {message.get('method')}")
    
    except asyncio.TimeoutError:
        logger.warning(f"Plugin connection from {peer} timed out during registration")
    except asyncio.CancelledError:
        logger.info(f"Plugin connection handler cancelled for {plugin_id or peer}")
    except Exception as e:
        logger.error(f"Error handling plugin connection {plugin_id or peer}: {e}")
    finally:
        # Cleanup
        if plugin_id:
            await plugin_manager.unregister(plugin_id)
        
        if not writer.is_closing():
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

# 开启socket服务
async def start_socket_server():
    """Start the plugin socket server as a background task."""
    global _unix_server, _tcp_server, _server_tasks
    
    if _server_tasks:
        logger.warning("Plugin socket server is already running")
        return
    
    try:
        socket_path = settings.PLUGIN_SOCKET_PATH
        tcp_port = settings.PLUGIN_TCP_PORT
        
        # 1. Start UNIX Socket Server (Internal Plugins)
        if socket_path:
            # Ensure directory exists
            socket_dir = os.path.dirname(socket_path)
            if socket_dir and not os.path.exists(socket_dir):
                os.makedirs(socket_dir, exist_ok=True)
            
            # Remove existing socket file
            if os.path.exists(socket_path):
                try:
                    # unlink() 方法用于删除指定路径的文件或符号链接，这里用于删除已存在的 Unix socket 文件，以便重新创建新的 socket。
                    os.unlink(socket_path)
                except Exception as e:
                    logger.error(f"Failed to remove existing socket file {socket_path}: {e}")
            # 开启 Unix socket 服务器，监听指定的 socket 文件路径，并将 _handle_client 作为连接处理函数。
            _unix_server = await asyncio.start_unix_server(
                _handle_client,
                path=socket_path,
            )
            
            # Set socket permissions (readable/writable by all)
            try:
                # os.chmod() 方法用于更改指定路径的文件或目录的权限，这里将 Unix socket 文件的权限设置为 666（所有用户可读写）。
                os.chmod(socket_path, 0o666)
            except Exception as e:
                logger.warning(f"Failed to set socket permissions: {e}")
            
            logger.info(f"Plugin socket server listening on UNIX {socket_path}")
            # 启动一个异步任务来运行 Unix socket 服务器，使用 async with 上下文管理器确保服务器在任务结束时正确关闭。
            async def serve_unix():
                async with _unix_server:
                    await _unix_server.serve_forever()
            
            _server_tasks.append(asyncio.create_task(serve_unix()))

        # 2. Start TCP Server (External Debug Plugins)
        # 如果配置了 TCP 端口，则开启 TCP 服务器，监听所有网络接口的指定端口，并将 _handle_client 作为连接处理函数。
        if tcp_port:
            _tcp_server = await asyncio.start_server(
                _handle_client,
                host="0.0.0.0",
                port=tcp_port,
            )
            logger.info(f"Plugin socket server listening on TCP 0.0.0.0:{tcp_port}")
            # 启动一个异步任务来运行 TCP 服务器，使用 async with 上下文管理器确保服务器在任务结束时正确关闭。
            async def serve_tcp():
                async with _tcp_server:
                    await _tcp_server.serve_forever()
            
            _server_tasks.append(asyncio.create_task(serve_tcp()))
        
        logger.info(f"Plugin socket server tasks started ({len(_server_tasks)} servers)")
    except Exception as e:
        logger.exception(f"Failed to start plugin socket server: {e}")

async def stop_socket_server():
    """Stop the plugin socket server."""
    global _unix_server, _tcp_server, _server_tasks
    
    # Stop the servers
    for server in [_unix_server, _tcp_server]:
        if server:
            server.close()
            try:
                await server.wait_closed()
            except Exception:
                pass
    
    _unix_server = None
    _tcp_server = None
    
    # Cancel the tasks
    for task in _server_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    _server_tasks = []
    
    # Remove socket file
    if os.path.exists(settings.PLUGIN_SOCKET_PATH):
        try:
            os.unlink(settings.PLUGIN_SOCKET_PATH)
        except Exception:
            pass
    
    logger.info("Plugin socket server stopped")

