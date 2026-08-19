from __future__ import annotations
import httpx
from typing import AsyncIterator

from app.domain.entities import ChatCompletionRequest
from app.domain.ports import TgoApiClient


class HttpxTgoApiClient(TgoApiClient):
    def __init__(self, base_url: str, timeout: float | None = None) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def chat_completion(self, req: ChatCompletionRequest) -> AsyncIterator[bytes]:
        url = "/v1/chat/completion"
        async with self._client.stream("POST", url, json=req.model_dump()) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line:
                    yield line.encode()

    async def aclose(self) -> None:
        await self._client.aclose()

