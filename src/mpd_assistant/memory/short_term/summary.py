"""Rolling summary of long conversations. Summarizes pseudonymized text only, so the summary holds no raw personal data."""

from typing import Any, Dict, List

from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.core.llm.client import LLM, LLMError

SUMMARY_TTL_SECONDS = 7 * 24 * 3600
KEEP_RECENT = 4
MAX_SUMMARY_CHARS = 900

SYSTEM = (
    "Summarize this conversation for the assistant's own later use in under 120 words: what the user wants, "
    "facts they gave, decisions made, and open questions. Keep placeholders like <EMAIL_1> exactly as written. "
    "Do not invent anything."
)


class RollingSummarizer:
    def __init__(self, llm: LLM, kv: KeyValueStore, every: int = 8):
        self._llm, self._kv, self._every = llm, kv, every

    def context_for(self, thread_id: str) -> str:
        stored = self._kv.get(f"summary:{thread_id}")
        return stored["text"] if stored else ""

    async def maybe_update(self, thread_id: str, messages: List[Dict[str, Any]]) -> bool:
        """Refresh the summary when enough new messages piled up. Returns whether it changed. Never raises."""
        stored = self._kv.get(f"summary:{thread_id}") or {"text": "", "upto": 0}
        older = messages[:-KEEP_RECENT] if len(messages) > KEEP_RECENT else []
        if len(older) - stored["upto"] < self._every:
            return False
        transcript = "\n".join(f"{m.get('role')}: {str(m.get('content', ''))[:400]}" for m in older[stored["upto"] :])
        prompt = f"Previous summary:\n{stored['text'] or '(none)'}\n\nNew messages:\n{transcript}"
        try:
            result = await self._llm.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                tier="cheap",
                max_tokens=220,
                temperature=0.0,
            )
        except LLMError:
            return False
        text = result.text.strip()[:MAX_SUMMARY_CHARS]
        if not text:
            return False
        self._kv.set(f"summary:{thread_id}", {"text": text, "upto": len(older)}, SUMMARY_TTL_SECONDS)
        return True
