"""Boundary enforcement (B2 LLM egress, B4 persistence): refuse raw personal data instead of sending it."""

from typing import Iterable, List

from mpd_assistant.core.llm.client import LLM, LLMResult
from mpd_assistant.observability.metrics import PII_DETECTIONS
from mpd_assistant.privacy.detector import detect


class RawPiiRefused(RuntimeError):
    def __init__(self, boundary: str, types: List[str]):
        super().__init__(f"raw personal data refused at {boundary}: {', '.join(sorted(set(types)))}")
        self.boundary = boundary
        self.types = types


def assert_tokenized(text: str, boundary: str, allowed: Iterable[str] = ()) -> None:
    allowed_set = set(allowed)
    found = [m for m in detect(text) if m.text not in allowed_set]
    if found:
        for m in found:
            PII_DETECTIONS.labels(boundary, m.type).inc()
        raise RawPiiRefused(boundary, [m.type for m in found])


class GuardedLLM:
    """Wraps any LLM so every outgoing message is checked before it leaves the process."""

    def __init__(self, inner: LLM, boundary: str = "B2_llm_egress"):
        self._inner, self._boundary = inner, boundary

    async def complete(self, messages, **kwargs) -> LLMResult:
        for message in messages:
            assert_tokenized(str(message.get("content", "")), self._boundary)
        return await self._inner.complete(messages, **kwargs)
