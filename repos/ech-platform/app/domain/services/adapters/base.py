from __future__ import annotations
from abc import ABC
from app.domain.entities import StreamEvent
from app.domain.ports import PlatformAdapter


class BasePlatformAdapter(PlatformAdapter, ABC):
    supports_stream: bool = False

# minimal adapter for testing, prints incremental/final outputs to stdout
class SimpleStdoutAdapter(BasePlatformAdapter):
    """Minimal adapter for MVP/testing. Prints incremental/final outputs."""

    async def send_incremental(self, ev: StreamEvent) -> None:  # pragma: no cover - side effect
        print(f"[INCR] event={ev.event} payload={ev.payload}")

    async def send_final(self, content: dict) -> None:  # pragma: no cover - side effect
        print(f"[FINAL] content={content}")

