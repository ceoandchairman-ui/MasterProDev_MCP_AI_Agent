"""Tool-result offloading: large outputs stay out of the prompt. The model sees a short digest and a reference, and the
full result can be re-opened on demand. Results are scoped to the conversation that produced them and expire."""

import json
import uuid
from typing import Any, Dict

from mpd_assistant.core.kv import KeyValueStore

TTL_SECONDS = 3600
DIGEST_CHARS = 1200
MAX_STORED_CHARS = 200_000


def digest(output: Any, limit: int = DIGEST_CHARS) -> str:
    """A compact, readable summary: list sizes and first items for collections, a clipped string otherwise."""
    if isinstance(output, dict):
        parts = []
        for key, value in output.items():
            if isinstance(value, list):
                head = json.dumps(value[:3], default=str, ensure_ascii=False)
                parts.append(f"{key}: {len(value)} items, first: {head}")
            else:
                parts.append(f"{key}: {json.dumps(value, default=str, ensure_ascii=False)[:200]}")
        text = "; ".join(parts)
    else:
        text = json.dumps(output, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ToolResultStore:
    def __init__(self, kv: KeyValueStore):
        self._kv = kv

    @staticmethod
    def _key(session_id: str, ref: str) -> str:
        return f"toolresult:{session_id}:{ref}"

    def put(self, session_id: str, tool: str, output: Dict[str, Any]) -> str | None:
        """Returns a reference, or None when the output is too large to keep at all."""
        serialized = json.dumps(output, default=str, ensure_ascii=False)
        if len(serialized) > MAX_STORED_CHARS:
            return None
        ref = uuid.uuid4().hex[:12]
        self._kv.set(self._key(session_id, ref), {"tool": tool, "output": json.loads(serialized)}, TTL_SECONDS)
        return ref

    def get(self, session_id: str, ref: str) -> Dict[str, Any] | None:
        """Only the owning conversation can re-open a result."""
        stored = self._kv.get(self._key(session_id, ref))
        return stored["output"] if stored else None


__all__ = ["ToolResultStore", "digest"]
