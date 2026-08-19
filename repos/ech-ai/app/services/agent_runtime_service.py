"""将 Supervisor Agent 执行请求转发至 Agent 服务的HTTP客户端。"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from app.config import settings
from app.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from app.schemas.agent_run import SupervisorRunRequest


logger = logging.getLogger(__name__)


class AgentRuntimeServiceClient:
    """封装对外部 Agent Runtime 服务的 HTTP 调用客户端。"""

    def __init__(self) -> None:
        self.base_url = settings.agent_service_url.rstrip("/")
        # Agent执行耗时较长，配置宽松超时参数
        self.request_timeout = httpx.Timeout(120.0, connect=10.0, write=30.0, read=120.0)
        self.stream_timeout = httpx.Timeout(None, connect=10.0, write=30.0, read=None)

    def _build_headers(
        self,
        api_key: str,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        headers = {
            "Content‑Type": "application/json",
            "X‑API‑Key": api_key,
            "User‑Agent": "tgo‑ai‑service",
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    async def run_supervisor(
        self,
        payload: SupervisorRunRequest,
        api_key: str,
        *,
        request_id: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        发起非流式 Supervisor Agent 执行请求。

        请求成功返回解析后的JSON字典；
        失败时会抛出业务域自定义异常，由上层统一捕获处理。
        """
        json_payload = payload.model_dump(mode="json", exclude_none=True)
        headers = self._build_headers(api_key, extra_headers)
        if request_id:
            headers.setdefault("X‑Request‑ID", request_id)

        url = f"{self.base_url}/run"
        logger.info(
            "转发非流式Supervisor执行请求", extra={"url": url, "request_id": request_id}
        )

        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.post(url, json=json_payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Agent服务请求超时", exc_info=exc)
            raise ExternalServiceError("agent", message="Agent service request timed out") from exc
        except httpx.RequestError as exc:
            logger.error("无法连接Agent服务", exc_info=exc)
            raise ExternalServiceError("agent", message="Unable to reach agent service") from exc

        if response.status_code >= 400:
            await self._raise_for_status(response)

        return response.json()

    async def stream_supervisor(
        self,
        payload: SupervisorRunRequest,
        api_key: str,
        *,
        request_id: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> AsyncIterator[str]:
        """流式获取Agent服务返回的Supervisor执行事件，返回字符串异步迭代器。"""
        json_payload = payload.model_dump(mode="json", exclude_none=True)
        json_payload["stream"] = True

        headers = self._build_headers(api_key, extra_headers)
        if request_id:
            headers.setdefault("X‑Request‑ID", request_id)

        url = f"{self.base_url}/run"
        logger.info(
            "转发流式Supervisor执行请求", extra={"url": url, "request_id": request_id}
        )

        async def event_stream() -> AsyncIterator[str]:
            try:
                async with httpx.AsyncClient(timeout=self.stream_timeout) as client:
                    async with client.stream("POST", url, json=json_payload, headers=headers) as response:
                        if response.status_code >= 400:
                            await self._raise_for_status(response)

                        async for chunk in response.aiter_text():
                            if chunk:
                                yield chunk
            except httpx.TimeoutException as exc:
                logger.error("Agent流式请求超时", exc_info=exc)
                raise ExternalServiceError("agent", message="Agent service stream timed out") from exc
            except httpx.RequestError as exc:
                logger.error("Agent流式连接异常", exc_info=exc)
                raise ExternalServiceError("agent", message="Unable to stream from agent service") from exc

        return event_stream()

    async def _raise_for_status(self, response: httpx.Response) -> None:
        """将HTTP错误响应转换为项目自定义业务异常。"""
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = {"detail": response.text or "Unknown error"}

        status_code = response.status_code
        detail = data.get("detail") if isinstance(data, dict) else data

        logger.warning(
            "Agent服务返回业务错误",
            extra={
                "status_code": status_code,
                "detail": detail,
            },
        )

        if status_code in (400, 422):
            raise ValidationError("Invalid request to agent service", details={"detail": detail})
        if status_code == 401:
            raise AuthenticationError(details={"service": "agent"})
        if status_code == 403:
            raise AuthorizationError(details={"service": "agent"})
        if status_code == 404:
            raise NotFoundError("AgentRun", None, {"detail": detail})
        if status_code == 429:
            raise RateLimitError(details={"service": "agent"})

        raise ExternalServiceError(
            "agent",
            message="Agent service returned an unexpected error",
            details={"status_code": status_code, "detail": detail},
        )


# 全局单例客户端实例
agent_runtime_service_client = AgentRuntimeServiceClient()