# =============================================================================
# 模块：Store 客户端 (Store Client)
# =============================================================================
# 该模块提供了与 Store API 服务通信的 HTTP 客户端，主要用于：
# 1. 工具（Tool）管理：获取工具详情、安装、卸载
# 2. 模型（Model）管理：获取模型详情、安装、卸载
# 3. Agent 管理：获取 Agent 详情、安装、卸载
# 4. 认证：通过访问令牌获取用户的 API Key
# 
# 设计目的：
# - 封装与 Store 服务的 HTTP 通信细节
# - 提供统一的接口用于工具、模型和 Agent 的生命周期管理
# - 支持从 Store 获取可用的 AI 组件并安装到项目中
# 
# 依赖服务：Store Service（集中管理工具、模型、Agent 的市场服务）
# =============================================================================

import httpx
from typing import Any, Dict, Optional, List

from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.store import StoreModelDetail, StoreAgentDetail

logger = get_logger("store_client")


# =============================================================================
# Store 客户端类
# =============================================================================

class StoreClient:
    """
    HTTP 客户端，用于与 Store API 服务通信。

    Store 是一个集中式的"应用商店"，提供：
    - AI 工具（Tools）：可被 Agent 调用的功能组件
    - AI 模型（Models）：LLM 模型配置
    - AI Agent：预构建的 AI 代理模板

    功能分组：
    1. 工具管理：获取详情、安装、卸载
    2. 模型管理：获取详情、安装、卸载
    3. Agent 管理：获取详情、安装、卸载
    4. 认证：获取 API Key

    配置来源：
    - base_url: 从环境变量 STORE_SERVICE_URL 读取
    - timeout: 从环境变量 STORE_TIMEOUT 读取
    """

    def __init__(self):
        """初始化 Store 客户端。"""
        self.base_url = f"{settings.STORE_SERVICE_URL.rstrip('/')}/api/v1"
        self.timeout = settings.STORE_TIMEOUT

    # =========================================================================
    # 1. 工具管理 (Tool Management)
    # =========================================================================

    async def get_tool(self, tool_id: str, api_key: str) -> Dict[str, Any]:
        """
        从 Store 获取工具详情。

        工具是可被 Agent 调用的功能组件，例如：
        - 搜索引擎工具
        - 数据库查询工具
        - 文件处理工具
        - 第三方 API 集成工具

        Args:
            tool_id: 工具 ID
            api_key: API Key（用于认证）

        Returns:
            Dict[str, Any]: 工具详细信息

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/tools/{tool_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    url,
                    headers={"X-API-Key": api_key}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (tools): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise

    async def install_tool(self, tool_id: str, api_key: str) -> Dict[str, Any]:
        """
        在 Store 中标记工具为已安装。

        当用户在项目中安装了某个工具后，调用此方法更新 Store 中的安装状态。
        这有助于：
        - 跟踪工具的使用情况
        - 防止重复安装
        - 提供安装统计

        Args:
            tool_id: 工具 ID
            api_key: API Key（用于认证）

        Returns:
            Dict[str, Any]: 安装结果

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/install/tool/{tool_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    url,
                    headers={"X-API-Key": api_key}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (install tool): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise

    async def uninstall_tool(self, tool_id: str, api_key: str) -> Dict[str, Any]:
        """
        在 Store 中标记工具为已卸载。

        当用户从项目中卸载了某个工具后，调用此方法更新 Store 中的状态。

        Args:
            tool_id: 工具 ID
            api_key: API Key（用于认证）

        Returns:
            Dict[str, Any]: 卸载结果

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/install/tool/{tool_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    "DELETE",
                    url,
                    headers={"X-API-Key": api_key}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (uninstall tool): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise

    # =========================================================================
    # 2. 模型管理 (Model Management)
    # =========================================================================

    async def get_model(self, model_id: str, api_key: str) -> StoreModelDetail:
        """
        从 Store 获取模型详情。

        模型是 LLM 的配置信息，包括：
        - 模型名称
        - 提供商
        - 参数配置
        - 价格信息
        - 能力描述

        Args:
            model_id: 模型 ID
            api_key: API Key（用于认证）

        Returns:
            StoreModelDetail: 模型详细信息（结构化对象）

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/models/{model_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    url,
                    headers={"X-API-Key": api_key}
                )
                response.raise_for_status()
                # 使用 Pydantic 模型验证响应数据
                return StoreModelDetail.model_validate(response.json())
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (models): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise

    async def install_model(self, model_id: str, api_key: str) -> Dict[str, Any]:
        """
        在 Store 中标记模型为已安装。

        Args:
            model_id: 模型 ID
            api_key: API Key（用于认证）

        Returns:
            Dict[str, Any]: 安装结果

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/install/model/{model_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    url,
                    headers={"X-API-Key": api_key}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (install model): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise

    async def uninstall_model(self, model_id: str, api_key: str) -> Dict[str, Any]:
        """
        在 Store 中标记模型为已卸载。

        Args:
            model_id: 模型 ID
            api_key: API Key（用于认证）

        Returns:
            Dict[str, Any]: 卸载结果

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/install/model/{model_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    "DELETE",
                    url,
                    headers={"X-API-Key": api_key}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (uninstall model): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise

    # =========================================================================
    # 3. Agent 管理 (Agent Management)
    # =========================================================================

    async def get_agent(self, agent_id: str, api_key: str) -> StoreAgentDetail:
        """
        从 Store 获取 Agent 详情。

        Agent 是预构建的 AI 代理模板，包含：
        - Agent 配置
        - 系统提示词
        - 工具列表
        - 模型配置
        - 示例对话

        用户可以从 Store 获取 Agent 模板并快速部署。

        Args:
            agent_id: Agent ID
            api_key: API Key（用于认证）

        Returns:
            StoreAgentDetail: Agent 详细信息（结构化对象）

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/agents/{agent_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    url,
                    headers={"X-API-Key": api_key}
                )
                response.raise_for_status()
                # 使用 Pydantic 模型验证响应数据
                return StoreAgentDetail.model_validate(response.json())
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (agents): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise

    async def install_agent(self, agent_id: str, api_key: str) -> Dict[str, Any]:
        """
        在 Store 中标记 Agent 为已安装。

        当用户从 Store 安装了一个 Agent 模板到自己的项目时，
        调用此方法更新 Store 中的安装状态。

        Args:
            agent_id: Agent ID
            api_key: API Key（用于认证）

        Returns:
            Dict[str, Any]: 安装结果

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/agents/{agent_id}/install"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    url,
                    headers={"X-API-Key": api_key}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (install agent): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise

    async def uninstall_agent(self, agent_id: str, api_key: str) -> Dict[str, Any]:
        """
        在 Store 中标记 Agent 为已卸载。

        Args:
            agent_id: Agent ID
            api_key: API Key（用于认证）

        Returns:
            Dict[str, Any]: 卸载结果

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/agents/{agent_id}/uninstall"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.request(
                    "DELETE",
                    url,
                    headers={"X-API-Key": api_key}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (uninstall agent): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise

    # =========================================================================
    # 4. 认证 (Authentication)
    # =========================================================================

    async def get_api_key(self, access_token: str) -> Dict[str, Any]:
        """
        使用访问令牌获取用户的 API Key。

        这个方法的典型使用场景：
        1. 用户通过 OAuth/SSO 登录获得 access_token
        2. 调用此方法从 Store 获取用户对应的 API Key
        3. 使用 API Key 进行后续的 Store API 调用

        这实现了：
        - 统一的用户认证
        - API Key 的安全管理
        - 用户与 Store 资源的关联

        Args:
            access_token: OAuth 访问令牌

        Returns:
            Dict[str, Any]: 包含用户 API Key 的响应

        Raises:
            httpx.HTTPStatusError: Store API 返回错误状态码
            Exception: 连接错误或其他异常
        """
        url = f"{self.base_url}/auth/api-key"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"Store API error (auth): {e.response.status_code} {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Store connection error: {str(e)}")
                raise


# =============================================================================
# 全局单例实例
# =============================================================================

# 导出全局单例，供其他模块使用
store_client = StoreClient()