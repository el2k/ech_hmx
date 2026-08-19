# =============================================================================
# 模块：设备控制服务客户端 (Device Control Service Client)
# =============================================================================
# 该模块提供了与 tgo-device-control 微服务通信的 HTTP 客户端，主要包括：
# 1. 设备管理（列表、查询、创建绑定码、更新、删除、断开连接）
# 2. Agent 操作（流式执行 Agent、获取设备工具、列出已连接设备）
# 
# 设计目的：
# - 封装与设备控制服务的 HTTP 通信细节
# - 提供统一的接口供其他模块调用
# - 处理错误、日志和超时
# 
# 依赖服务：tgo-device-control（设备控制微服务）
# 源码路径：/data/hmx/Test_el2k/tgo-study/repos/tgo-device-control
# =============================================================================

from typing import Any, AsyncGenerator, Dict, Optional
import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("services.device_control_client")


# =============================================================================
# 设备控制客户端类
# =============================================================================

class DeviceControlClient:
    """
    HTTP 客户端，用于与 tgo-device-control 服务通信。

    功能分组：
    1. 设备管理：增删改查设备，生成绑定码，断开连接
    2. Agent 操作：远程执行 Agent，获取工具列表

    配置来源：
    - base_url: 从环境变量 DEVICE_CONTROL_SERVICE_URL 读取
    - timeout: 从环境变量 DEVICE_CONTROL_SERVICE_TIMEOUT 读取
    """

    def __init__(self):
        """
        初始化设备控制客户端。

        配置说明：
        - 这些配置通过 Pydantic BaseSettings 管理，从环境变量或 .env 中读取
        - 不是数据库字段，而是微服务之间通信的服务发现地址
        - tgo-api 通过 DEVICE_CONTROL_SERVICE_URL 构造 HTTP Client
        - 请求 tgo-device-control 的设备列表、绑定码生成、远程 Agent 执行等接口
        """
        # 移除末尾的斜杠，方便 URL 拼接
        self.base_url = settings.DEVICE_CONTROL_SERVICE_URL.rstrip("/")
        self.timeout = settings.DEVICE_CONTROL_SERVICE_TIMEOUT

    # =========================================================================
    # 内部请求方法
    # =========================================================================

    async def _request(
        self,
        method: str,  # HTTP 方法：GET, POST, PATCH, DELETE 等
        path: str,    # API 路径（如 "/v1/devices"）
        params: Optional[Dict[str, Any]] = None,  # URL 查询参数
        json: Optional[Dict[str, Any]] = None,    # JSON 请求体
    ) -> Optional[Dict[str, Any]]:
        """
        向设备控制服务发起 HTTP 请求的内部方法。

        执行流程：
        1. 拼接完整的请求 URL
        2. 使用 httpx.AsyncClient 发起异步 HTTP 请求
        3. 检查响应状态码（4xx/5xx 抛出异常）
        4. 解析并返回 JSON 响应

        错误处理：
        - HTTPStatusError: 服务返回错误状态码（4xx/5xx）
        - RequestError: 网络连接错误

        Args:
            method: HTTP 方法
            path: API 路径
            params: URL 查询参数
            json: JSON 请求体

        Returns:
            Optional[Dict[str, Any]]: 解析后的 JSON 响应

        Raises:
            httpx.HTTPStatusError: HTTP 错误响应
            httpx.RequestError: 连接错误
        """
        url = f"{self.base_url}{path}"

        # 使用异步 HTTP 客户端
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # 发起请求
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                )
                # 检查状态码（4xx/5xx 抛出异常）
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                # HTTP 错误（如 404, 500）
                logger.error(
                    f"Device control service error: {e.response.status_code} - {e.response.text}"
                )
                raise
            except httpx.RequestError as e:
                # 连接错误（如超时、DNS 解析失败）
                logger.error(f"Device control service connection error: {e}")
                raise

    # =========================================================================
    # 设备管理 API
    # =========================================================================

    async def list_devices(
        self,
        project_id: str,
        device_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        获取项目的设备列表。

        支持过滤和分页。

        Args:
            project_id: 项目 ID
            device_type: 设备类型过滤（可选）
            status: 设备状态过滤（可选）
            skip: 分页偏移量
            limit: 每页数量

        Returns:
            Dict[str, Any]: 设备列表响应
        """
        params = {
            "project_id": project_id,
            "skip": skip,
            "limit": limit,
        }
        if device_type:
            params["device_type"] = device_type
        if status:
            params["status"] = status

        return await self._request("GET", "/v1/devices", params=params)

    async def get_device(
        self,
        device_id: str,
        project_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        获取特定设备的详细信息。

        Args:
            device_id: 设备 ID
            project_id: 项目 ID（用于权限验证）

        Returns:
            Optional[Dict[str, Any]]: 设备信息
        """
        params = {"project_id": project_id}
        return await self._request("GET", f"/v1/devices/{device_id}", params=params)

    async def generate_bind_code(self, project_id: str) -> Dict[str, Any]:
        """
        生成设备注册绑定码。

        绑定码用于设备首次注册时的身份验证。
        设备端使用绑定码向服务端发起连接请求。

        Args:
            project_id: 项目 ID

        Returns:
            Dict[str, Any]: 包含绑定码的响应
        """
        params = {"project_id": project_id}
        return await self._request("POST", "/v1/devices/bind-code", params=params)

    async def update_device(
        self,
        device_id: str,
        project_id: str,
        data: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        更新设备信息。

        可用于更新设备名称、状态、配置等。

        Args:
            device_id: 设备 ID
            project_id: 项目 ID（用于权限验证）
            data: 要更新的字段

        Returns:
            Optional[Dict[str, Any]]: 更新后的设备信息
        """
        params = {"project_id": project_id}
        return await self._request(
            "PATCH", f"/v1/devices/{device_id}", params=params, json=data
        )

    async def delete_device(
        self,
        device_id: str,
        project_id: str,
    ) -> bool:
        """
        删除设备。

        从系统中移除设备记录。

        Args:
            device_id: 设备 ID
            project_id: 项目 ID（用于权限验证）

        Returns:
            bool: 删除成功返回 True
        """
        params = {"project_id": project_id}
        await self._request("DELETE", f"/v1/devices/{device_id}", params=params)
        return True

    async def disconnect_device(
        self,
        device_id: str,
        project_id: str,
    ) -> bool:
        """
        强制断开设备连接。

        用于远程强制设备离线，常用于设备管理或故障恢复场景。

        Args:
            device_id: 设备 ID
            project_id: 项目 ID（用于权限验证）

        Returns:
            bool: 断开成功返回 True
        """
        params = {"project_id": project_id}
        await self._request(
            "POST", f"/v1/devices/{device_id}/disconnect", params=params
        )
        return True

    # =========================================================================
    # Agent 操作 API
    # =========================================================================

    async def run_agent_stream(
        self,
        device_id: str,
        task: str,
        provider_id: Optional[str] = None,
        model: Optional[str] = None,
        project_id: Optional[str] = None,
        max_iterations: Optional[int] = None,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        在设备上运行 MCP Agent，返回流式响应。

        这是一个关键方法，用于远程控制设备执行任务。
        Agent 会通过 MCP（Model Context Protocol）与设备交互，
        执行一系列操作来完成用户指定的任务。

        工作流程：
        1. 设备端运行 MCP Agent
        2. Agent 调用 LLM 进行任务规划
        3. Agent 通过 MCP 调用设备工具
        4. 结果通过 SSE 流式返回

        Args:
            device_id: 要控制的设备 ID
            task: 要执行的任务描述
            provider_id: AI Provider ID（用于 LLM 调用）
            model: 使用的 LLM 模型
            project_id: 项目 ID（用于权限验证）
            max_iterations: 最大迭代次数（防止无限循环）
            system_prompt: 自定义系统提示词

        Yields:
            SSE 事件字符串（每行一个事件）

        Raises:
            httpx.HTTPStatusError: 服务返回错误
            httpx.RequestError: 连接错误
        """
        url = f"{self.base_url}/v1/agent/run"

        # 构建请求载荷
        payload: Dict[str, Any] = {
            "device_id": device_id,
            "task": task,
            "stream": True,  # 启用流式响应
        }
        if provider_id:
            payload["provider_id"] = provider_id
        if model:
            payload["model"] = model
        if project_id:
            payload["project_id"] = project_id
        if max_iterations:
            payload["max_iterations"] = max_iterations
        if system_prompt:
            payload["system_prompt"] = system_prompt

        # Agent 操作可能需要较长时间，使用更长的超时时间
        # 总超时 300 秒，连接超时 10 秒
        timeout = httpx.Timeout(300.0, connect=10.0)

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                # 使用流式请求
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers={"Accept": "text/event-stream"},
                ) as response:
                    response.raise_for_status()
                    # 逐行读取 SSE 事件
                    async for line in response.aiter_lines():
                        if line:
                            yield line
            except httpx.HTTPStatusError as e:
                # 在流式模式下，需要先读取响应体才能访问 .text
                await e.response.aread()
                logger.error(
                    f"Device control agent error: {e.response.status_code} - {e.response.text}"
                )
                raise
            except httpx.RequestError as e:
                logger.error(f"Device control agent connection error: {e}")
                raise

    async def get_device_tools(
        self,
        device_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        获取已连接设备上可用的工具列表。

        工具列表由设备上的 MCP 服务器提供，
        包括设备支持的所有可调用功能。

        Args:
            device_id: 设备 ID

        Returns:
            Optional[Dict[str, Any]]: 工具列表
        """
        return await self._request("GET", f"/v1/agent/devices/{device_id}/tools")

    async def list_connected_devices(self) -> Dict[str, Any]:
        """
        列出所有可用于 Agent 控制的已连接设备。

        返回当前在线且可被 Agent 远程控制的设备列表。

        Returns:
            Dict[str, Any]: 已连接设备列表
        """
        return await self._request("GET", "/v1/agent/devices")


# =============================================================================
# 全局单例实例
# =============================================================================

# 导出全局单例，供其他模块使用
device_control_client = DeviceControlClient()