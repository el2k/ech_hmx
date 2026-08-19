"""API Service client for interacting with the core TGO API service."""

import logging
from typing import Any, Dict, Optional

import httpx
from app.config import settings

logger = logging.getLogger("services.api_service")
# APIServiceClient类用于与核心TGO API服务进行交互，提供获取存储凭证和执行插件工具的功能。
class APIServiceClient:
    # 客户端类，用于与核心TGO API服务进行交互
    """Client for interacting with the core TGO API service."""

    def __init__(self):
        """Initialize the API service client."""
        # 初始化API服务客户端
        # 使用docker服务名称而不是localhost进行内部通信
        # Use docker service name instead of localhost for internal communication
        self.api_base_url = settings.api_service_url
        internal_base = (settings.api_internal_service_url or self.api_base_url).rstrip("/")
        self.internal_api_url = f"{internal_base}/internal"
            
        self.plugin_runtime_url = settings.plugin_runtime_url
        self.timeout = 30.0

    async def get_store_credential(self, project_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch store credential for a project from the internal API.
        """
        # 抓取项目的存储凭证
        urls = [f"{self.internal_api_url}/store/{project_id}/credential"]
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for url in urls:
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        return response.json()
                except Exception:
                    continue
            
            logger.error(f"Failed to fetch store credential from all candidate URLs for project {project_id}")
            return None

    async def execute_plugin_tool(
        self,
        plugin_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        执行插件工具，通过TGO插件运行时服务。
        参数:
            plugin_id: 唯一的插件ID
            tool_name: 要执行的工具名称
            arguments: 来自LLM的工具参数
            context: 包含user_id、session_id、agent_id等的上下文信息
        返回:
            工具结果字典
        
        Execute a plugin tool via the TGO Plugin Runtime service.

        Args:
            plugin_id: Unique plugin ID
            tool_name: Name of the tool to execute
            arguments: Tool arguments from LLM
            context: Context containing user_id, session_id, agent_id, etc.

        Returns:
            Tool result dictionary
        """
        url = f"{self.plugin_runtime_url}/plugins/tools/execute/{plugin_id}/{tool_name}"
        
        payload = {
            "arguments": arguments,
            "context": context,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"API service error executing plugin tool: {response.status_code} {response.text}")
                    return {
                        "success": False,
                        "error": f"API service error: {response.status_code}",
                        "content": f"工具执行失败 (HTTP {response.status_code})"
                    }

            except httpx.RequestError as e:
                logger.error(f"Unable to connect to API service: {str(e)}")
                return {
                    "success": False,
                    "error": str(e),
                    "content": "无法连接到 TGO API 服务"
                }

# Global API service client instance
api_service_client = APIServiceClient()
