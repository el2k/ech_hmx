"""Process Manager - Manages plugin processes and their lifecycle."""

import asyncio
import os
import signal
import collections
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger
from app.config import settings
from app.core.database import SessionLocal
from app.models.plugin import InstalledPlugin

logger = get_logger("services.process_manager")

# dataclass 指定了一个名为 ManagedPlugin 的数据类，用于表示由该服务管理的插件进程。它包含以下字段：
@dataclass
class ManagedPlugin:
    """Represents a plugin process managed by this service."""
    id: str
    config: Dict[str, Any]
    process: Optional[asyncio.subprocess.Process] = None
    status: str = "stopped"  # stopped, running, starting, error
    pid: Optional[int] = None
    last_error: Optional[str] = None
    restart_count: int = 0
    logs: collections.deque = field(default_factory=lambda: collections.deque(maxlen=1000))
    _stop_requested: bool = False

class ProcessManager:
    """Service to manage plugin processes."""
    # 服务类 ProcessManager 用于管理插件进程的生命周期。它包含以下主要功能：
    # - 启动和停止插件进程。
    # - 监控插件进程的状态，并在进程意外退出时自动重启。
    # - 维护插件的运行状态、日志和错误信息。
    # - 提供获取插件状态和日志的接口。
    # 该类使用 asyncio 进行异步操作，并通过数据库更新插件的状态。
    def __init__(self, base_path: str = "/var/lib/tgo/plugins"):
        self.base_path = Path(base_path)
        self._managed_plugins: Dict[str, ManagedPlugin] = {}
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the process monitor task."""
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            logger.info("Process manager monitor loop started")

    async def stop(self):
        """Stop all managed plugins and the monitor task."""
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None
            
        async with self._lock:
            # 停止所有管理的插件进程，调用 _stop_plugin_inner 方法逐个停止插件。
            for plugin_id in list(self._managed_plugins.keys()):
                await self._stop_plugin_inner(plugin_id)
        
        logger.info("Process manager stopped")
    # 更新数据库中的插件状态
    async def _update_db_status(self, plugin_id: str, status: str, pid: Optional[int] = None, last_error: Optional[str] = None):
        """Update plugin status in database."""
        try:
            with SessionLocal() as db:
                plugin = db.query(InstalledPlugin).filter(InstalledPlugin.plugin_id == plugin_id).first()
                if plugin:
                    plugin.status = status
                    plugin.pid = pid
                    if last_error is not None:
                        plugin.last_error = last_error
                    db.commit()
        except Exception as e:
            logger.error(f"Failed to update DB status for {plugin_id}: {e}")
    # 监控循环，定期检查插件进程的状态，并在进程意外退出时自动重启。
    async def _monitor_loop(self):
        """Monitor running processes and auto-restart if needed."""
        while True:
            try:
                await asyncio.sleep(5)
                # 使用 asyncio 锁来确保对 _managed_plugins 的访问是线程安全的。
                # 遍历所有管理的插件，检查其状态。如果插件正在运行但进程已经退出（即 returncode 不为 None），则将其状态更新为 "error"，
                # 并记录错误信息。如果插件配置了自动重启（auto_restart 为 True），则在指定的延迟后重新启动插件。
                async with self._lock:
                    for plugin_id, managed in list(self._managed_plugins.items()):
                        if managed.status == "running" and managed.process:
                            # Check if process is still alive
                            # returncode 为 None 表示进程仍在运行，如果 returncode 不为 None，则表示进程已经退出。
                            if managed.process.returncode is not None:
                                logger.warning(f"Plugin {plugin_id} exited with code {managed.process.returncode}")
                                managed.status = "error"
                                managed.pid = None
                                # 更新数据库中的插件状态为 "error"，并记录最后的错误信息。
                                await self._update_db_status(plugin_id, "error", pid=None, last_error=f"Exited with code {managed.process.returncode}")
                                
                                # Auto restart if configured
                                runtime_config = managed.config.get("runtime", {})
                                if runtime_config.get("auto_restart", True) and not managed._stop_requested:
                                    delay = runtime_config.get("restart_delay", 5)
                                    logger.info(f"Auto-restarting plugin {plugin_id} in {delay}s...")
                                    asyncio.create_task(self._delayed_restart(plugin_id, delay))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in process monitor loop: {e}")

    async def _delayed_restart(self, plugin_id: str, delay: int):
        """Restart a plugin after a delay."""
        await asyncio.sleep(delay)
        async with self._lock:
            if plugin_id in self._managed_plugins:
                await self._start_plugin_inner(plugin_id, self._managed_plugins[plugin_id].config)

    async def start_plugin(self, plugin_id: str, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Start a plugin process."""
        async with self._lock:
            return await self._start_plugin_inner(plugin_id, config)
    # _start_plugin_inner 方法是 ProcessManager 类中的一个内部方法，用于启动插件进程。它执行以下操作：
    # 1. 检查插件是否已经在管理中，如果是且状态为 "running"，则返回 "Already running"。
    # 2. 如果插件不在管理中，则创建一个新的 ManagedPlugin 实例，并将其添加到 _managed_plugins 字典中
    # 3. 更新插件的配置和状态为 "starting"。
    # 4. 准备启动命令，根据插件的构建配置（build_config）确定插件的语言（Go、Python、Node.js 等），并构建相应的启动命令。
    # 5. 设置环境变量，包括插件 SDK 的套接字路径和 TCP 端口。
    # 6. 使用 asyncio.create_subprocess_exec 启动插件进程，并将其 stdout 和 stderr 重定向到管道中，以便后续读取日志。
    # 7. 如果启动成功，将插件状态更新为 "running"，并启动一个异步任务来读取插件的日志输出。
    # 8. 如果启动失败，将插件状态更新为 "error"，并记录错误信息。
    async def _start_plugin_inner(self, plugin_id: str, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Internal start_plugin without lock."""
        if plugin_id in self._managed_plugins:
            managed = self._managed_plugins[plugin_id]
            if managed.status == "running":
                return True, "Already running"
        else:
            managed = ManagedPlugin(id=plugin_id, config=config)
            self._managed_plugins[plugin_id] = managed
        
        managed.config = config  # Update config
        managed.status = "starting"
        managed._stop_requested = False
        
        # Prepare command
        install_dir = self.base_path / plugin_id
        if not install_dir.exists():
            managed.status = "error"
            managed.last_error = f"Install directory not found: {install_dir}"
            return False, managed.last_error
        
        build_config = config.get("build", {})
        runtime_config = config.get("runtime", {})
        lang = build_config.get("language", "").lower()
        
        cmd = []
        env = os.environ.copy()
        env.update(runtime_config.get("env", {}))
        
        # Set socket path for plugin SDK to connect
        # 设置插件 SDK 的套接字路径和 TCP 端口，以便插件可以与主服务进行通信。
        env["TGO_SOCKET_PATH"] = settings.PLUGIN_SOCKET_PATH
        if settings.PLUGIN_TCP_PORT:
            env["TGO_TCP_PORT"] = str(settings.PLUGIN_TCP_PORT)
        # 如果插件的语言是 Go，则尝试找到编译后的二进制文件作为入口点。如果找不到指定的二进制文件，则尝试使用默认的 "plugin" 文件名。如果仍然找不到，则将插件状态设置为 "error" 并返回错误信息。
        # 如果插件的语言是 Python，则尝试找到指定的入口点脚本，并使用虚拟环境中的 Python 解释器来启动该脚本。如果找不到虚拟环境中的 Python 解释器，则使用系统的 "python3" 命令。
        # 如果插件的语言是 Node.js，则尝试找到指定的入口点脚本，并使用 "node" 命令来启动该脚本。
        # 如果插件的语言不是上述三种，则尝试使用默认的 "plugin" 二进制文件作为入口点。如果找不到该文件，则将插件状态设置为 "error" 并返回错误信息。
        if lang == "go":
            # Entrypoint is the compiled binary
            binary_name = build_config.get("go", {}).get("output", "plugin")
            binary_path = install_dir / binary_name
            if not binary_path.exists():
                # Fallback to 'plugin'
                binary_path = install_dir / "plugin"
            
            if not binary_path.exists():
                managed.status = "error"
                managed.last_error = f"Plugin binary not found: {binary_path}"
                return False, managed.last_error
            
            cmd = [str(binary_path)]
            
        elif lang == "python":
            entrypoint = build_config.get("python", {}).get("entrypoint", "main.py")
            # 这里尝试找到插件的虚拟环境中的 Python 解释器路径，如果不存在，则使用系统的 "python3" 命令。然后构建启动命令，将 Python 解释器和入口点脚本作为命令参数。
            python_path = install_dir / ".venv" / "bin" / "python3"
            if not python_path.exists():
                python_path = "python3"
            
            cmd = [str(python_path), entrypoint]
            
        elif lang == "nodejs":
            entrypoint = build_config.get("nodejs", {}).get("entrypoint", "index.js")
            cmd = ["node", entrypoint]
        else:
            # Default to binary install
            binary_path = install_dir / "plugin"
            if not binary_path.exists():
                managed.status = "error"
                managed.last_error = "No entrypoint or binary found for plugin"
                return False, managed.last_error
            cmd = [str(binary_path)]
        
        # Add arguments
        cmd.extend(runtime_config.get("args", []))
        
        logger.info(f"Starting plugin {plugin_id}: {' '.join(cmd)}")
        
        try:
            # 创建一个异步子进程来执行插件的启动命令，并将其工作目录设置为插件的安装目录，环境变量设置为之前准备好的环境变量。
            # 将子进程的 stdout 和 stderr 重定向到管道中，以便后续读取日志。
            # create_subprocess_exec 会立即启动这个子进程。
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(install_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            managed.process = process
            managed.pid = process.pid
            managed.status = "running"
            managed.restart_count += 1
            await self._update_db_status(plugin_id, "running", pid=managed.pid)
            
            # Start logging task
            # 创建一个异步任务来读取插件进程的日志输出，并将其存储在 ManagedPlugin 实例的 logs 队列中，以便后续获取日志。
            asyncio.create_task(self._read_logs(managed))
            
            return True, "Started successfully"
        except Exception as e:
            managed.status = "error"
            managed.last_error = f"Failed to start: {str(e)}"
            logger.error(f"Failed to start plugin {plugin_id}: {e}")
            await self._update_db_status(plugin_id, "error", last_error=managed.last_error)
            return False, managed.last_error
    # 读取日志
    async def _read_logs(self, managed: ManagedPlugin):
        """Read process output and store in buffer."""
        if not managed.process or not managed.process.stdout:
            return
            
        while True:
            line = await managed.process.stdout.readline()
            if not line:
                break
            
            decoded_line = line.decode().strip()
            managed.logs.append(decoded_line)
            # Optional: also log to system logger
            # logger.debug(f"[{managed.id}] {decoded_line}")
    # 停止插件
    async def stop_plugin(self, plugin_id: str) -> bool:
        """Stop a plugin process."""
        async with self._lock:
            return await self._stop_plugin_inner(plugin_id)
    # _stop_plugin_inner 方法是 ProcessManager 类中的一个内部方法，用于停止插件进程。它执行以下操作：
    # 1. 检查插件是否在管理中，如果不在或状态为 "stopped"，则直接返回 True。
    # 2. 将 _stop_requested 标志设置为 True，表示用户请求停止插件。
    # 3. 如果插件进程仍在运行（即 returncode 为 None），则尝试终止该进程。如果在指定的超时时间内进程没有退出，则强制杀死该进程。
    # 4. 更新插件的状态为 "stopped"，并将 pid 和 process 设置为 None。
    # 5. 更新数据库中的插件状态为 "stopped"。
    async def _stop_plugin_inner(self, plugin_id: str) -> bool:
        """Internal stop_plugin without lock."""
        managed = self._managed_plugins.get(plugin_id)
        if not managed or managed.status == "stopped":
            return True
        
        managed._stop_requested = True
        if managed.process and managed.process.returncode is None:
            logger.info(f"Stopping plugin {plugin_id} (pid={managed.pid})")
            try:
                # 停止插件进程，首先调用 terminate() 方法发送终止信号，然后等待进程退出。如果在指定的超时时间内进程没有退出，则调用 kill() 方法强制杀死进程。
                managed.process.terminate()
                try:
                    await asyncio.wait_for(managed.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    managed.process.kill()
                    await managed.process.wait()
            except Exception as e:
                logger.error(f"Error stopping plugin {plugin_id}: {e}")
        
        managed.status = "stopped"
        managed.pid = None
        managed.process = None
        await self._update_db_status(plugin_id, "stopped", pid=None)
        return True
    # restart_plugin 方法是 ProcessManager 类中的一个方法，用于重新启动插件进程。它执行以下操作：
    # 1. 获取插件的 ManagedPlugin 实例，如果插件不在管理中，则返回 False 和 "Plugin not managed"。
    # 2. 调用 _stop_plugin_inner 方法停止插件进程。
    # 3. 调用 _start_plugin_inner 方法重新启动插件进程，并传入之前保存的配置。
    # 4. 返回重新启动的结果和状态信息。
    async def restart_plugin(self, plugin_id: str) -> Tuple[bool, str]:
        """Restart a plugin process."""
        async with self._lock:
            managed = self._managed_plugins.get(plugin_id)
            if not managed:
                return False, "Plugin not managed"
            
            config = managed.config
            await self._stop_plugin_inner(plugin_id)
            return await self._start_plugin_inner(plugin_id, config)
    # get_logs 方法是 ProcessManager 类中的一个方法，用于获取插件的最新日志。它执行以下操作：
    # 1. 获取插件的 ManagedPlugin 实例，如果插件不在管理中，则返回一个空列表。
    # 2. 返回 ManagedPlugin 实例的 logs 队列中的日志内容，转换为列表形式。
    # 3. 该方法提供了一个接口，允许外部调用者获取插件的日志输出，以便进行调试和监控。
    def get_logs(self, plugin_id: str) -> List[str]:
        """Get the latest logs for a plugin."""
        managed = self._managed_plugins.get(plugin_id)
        if managed:
            return list(managed.logs)
        return []
    # get_status 方法是 ProcessManager 类中的一个方法，用于获取插件的运行状态。它执行以下操作：
    # 1. 获取插件的 ManagedPlugin 实例，如果插件不在管理中，则返回一个字典，表示插件未被管理。
    # 2. 返回一个字典，包含插件的 id、状态、进程 ID、重启次数和最后的错误信息（如果有的话）。
    # 3. 该方法提供了一个接口，允许外部调用者获取插件的运行状态，以便进行监控和管理。
    def get_status(self, plugin_id: str) -> Dict[str, Any]:
        """Get the status of a plugin."""
        managed = self._managed_plugins.get(plugin_id)
        if managed:
            return {
                "id": managed.id,
                "status": managed.status,
                "pid": managed.pid,
                "restart_count": managed.restart_count,
                "last_error": managed.last_error
            }
        return {"id": plugin_id, "status": "not_managed"}


# Global instance
from app.config import settings as _settings
# 创建一个全局的 ProcessManager 实例，使用配置文件中指定的插件基础路径作为参数。这个实例将在整个应用程序中被共享，用于管理所有插件的进程生命周期。
process_manager = ProcessManager(base_path=_settings.PLUGIN_BASE_PATH)

