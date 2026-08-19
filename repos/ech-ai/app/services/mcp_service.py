"""
MCP Service Client

本模块提供与 MCP (Model Context Protocol，模型上下文协议) 服务交互的客户端。
封装向MCP服务发起HTTP请求，用于调用工具以及其它MCP相关业务操作。
"""

import logging
from typing import Any, Dict, List, Optional
import httpx
from fastapi import HTTPException

from app.config import settings

# 模块日志记录器
logger = logging.getLogger(__name__)


class MCPServiceError(Exception):
    """MCP服务调用异常，业务自定义异常。
    封装错误消息、HTTP状态码、下游返回的原始响应数据，方便上层做错误处理。
    """

    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict[str, Any]] = None):
        self.message = message          # 错误描述文本
        self.status_code = status_code  # MCP服务返回HTTP状态码
        self.response_data = response_data  # MCP返回的原始错误载荷
        super().__init__(message)


class MCPServiceClient:
    """MCP服务HTTP客户端，用于访问远端MCP微服务。"""

    def __init__(self):
        # 读取配置中的MCP服务地址，去除末尾斜杠，避免拼接URL出现双斜杠
        self.base_url = settings.mcp_service_url.rstrip('/')
        # HTTP请求超时时间，单位秒
        self.timeout = 30.0

    def _get_headers(self, additional_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """构造MCP服务请求通用请求头（当前版本无鉴权）。

        :param additional_headers: 需要额外追加的自定义请求头字典
        :return: 组装完成的完整请求头
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "TGO-AI-Service/1.0"
        }

        # 如果传入额外头，合并到基础头中
        if additional_headers:
            headers.update(additional_headers)

        return headers

    async def _make_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        底层通用请求方法，封装对MCP服务的HTTP调用。
        统一处理请求发送、状态码分支处理、网络异常捕获，向上抛出MCPServiceError。

        Args:
            method: HTTP请求方法，例如 GET / POST / PUT / DELETE
            path: API接口相对路径，例如 "/v1/tools"
            params: URL查询参数，字典格式
            json_data: 请求体JSON载荷，会自动序列化为body
            headers: 额外追加的请求头

        Returns:
            Dict[str, Any]: MCP服务返回的JSON解析后字典

        Raises:
            MCPServiceError: 网络异常、下游返回非成功状态码时抛出该自定义异常
        """
        # 拼接完整请求URL：基础地址 + 接口相对路径
        url = f"{self.base_url}{path}"
        # 获取组装好的请求头
        request_headers = self._get_headers(headers)

        try:
            # 创建异步httpx客户端实例，设置超时
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(f"Making {method} request to MCP service: {url}")

                # 发起http请求
                response = await client.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    params=params,
                    json=json_data
                )

                logger.info(f"MCP service responded with status: {response.status_code}")

                # ========== 状态码分支处理 ==========
                # 正常返回200，直接返回解析后的json字典
                if response.status_code == 200:
                    return response.json()
                # 创建类接口返回201，同样返回json
                elif response.status_code == 201:
                    return response.json()
                # 无内容204，返回空字典，避免上层读取json报错
                elif response.status_code == 204:
                    return {}
                # 404资源不存在，封装异常携带下游返回数据
                elif response.status_code == 404:
                    raise MCPServiceError(
                        "Resource not found in MCP service",
                        status_code=404,
                        response_data=response.json() if response.content else None
                    )
                # 400参数错误，提取detail错误信息
                elif response.status_code == 400:
                    error_data = response.json() if response.content else {}
                    raise MCPServiceError(
                        f"Bad request to MCP service: {error_data.get('detail', 'Invalid request')}",
                        status_code=400,
                        response_data=error_data
                    )
                # 5xx服务端内部错误
                elif response.status_code >= 500:
                    raise MCPServiceError(
                        "MCP service internal error",
                        status_code=response.status_code
                    )
                # 其它未覆盖的状态码统一兜底
                else:
                    error_data = response.json() if response.content else {}
                    raise MCPServiceError(
                        f"MCP service error: {error_data.get('detail', 'Unknown error')}",
                        status_code=response.status_code,
                        response_data=error_data
                    )

        # 请求超时：映射为网关超时504
        except httpx.TimeoutException:
            logger.error(f"Timeout when calling MCP service: {url}")
            raise MCPServiceError(
                "MCP service request timed out",
                status_code=504
            )
        # 连接失败，无法建立TCP连接：映射为网关错误502
        except httpx.ConnectError:
            logger.error(f"Connection error when calling MCP service: {url}")
            raise MCPServiceError(
                "Unable to connect to MCP service",
                status_code=502
            )
        # 如果已经是MCPServiceError，直接重新抛出，不做二次包装
        except MCPServiceError:
            raise
        # 其余未预期异常，统一捕获包装为MCP业务异常
        except Exception as e:
            logger.error(f"Unexpected error when calling MCP service: {e}")
            raise MCPServiceError(
                f"MCP service request failed: {str(e)}",
                status_code=500
            )


# 全局单例客户端实例，业务层直接导入使用 mcp_service_client
mcp_service_client = MCPServiceClient()