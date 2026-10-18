"""API-boundary service: pseudonymize on the way in, restore values only in the reply to this user.

The graph, its checkpoints and every model call only ever see tokens such as <EMAIL_1>.
"""

import time
from dataclasses import dataclass
from typing import Any, List

from mpd_assistant.evaluation.online.rules import Verdict, evaluate_response
from mpd_assistant.observability.metrics import record_turn
from mpd_assistant.privacy.vault import PiiVault
from mpd_assistant.responses.engine import render


@dataclass
class ChatResult:
    reply: str
    escalated: bool
    reference: str | None
    eval_reasons: List[str]
    safe_user_text: str = ""
    intent: str = ""
    agent: str = ""
    mode: str = ""


class ChatService:
    def __init__(self, graph: Any, vault: PiiVault):
        self._graph = graph
        self._vault = vault

    async def chat(self, session_id: str, raw_text: str, verified: bool = False, user_id: str | None = None) -> ChatResult:
        started = time.perf_counter()
        safe_text = self._vault.tokenize(session_id, raw_text)
        out = await self._graph.ainvoke(
            {"messages": [{"role": "user", "content": safe_text}], "session_id": session_id, "verified": verified, "user_id": user_id},
            config={"configurable": {"thread_id": session_id}},
        )
        reply = self._vault.detokenize(session_id, out.get("response") or "")
        final = evaluate_response(reply, language=out.get("language", "en"), allowed_pii=self._vault.known_values(session_id))
        if final.verdict is not Verdict.PASS:
            reply = render("temporary_error", out.get("language", "en"))
        reasons = list(out.get("eval_reasons", [])) + final.reasons
        record_turn(
            agent=out.get("agent", "unknown"),
            mode=out.get("mode", "unknown"),
            intent=out.get("intent", "unknown"),
            seconds=time.perf_counter() - started,
            verdict=out.get("eval_verdict"),
            escalated=bool(out.get("escalated")),
            reasons=reasons,
        )
        return ChatResult(
            reply,
            bool(out.get("escalated")),
            out.get("reference"),
            reasons,
            safe_user_text=safe_text,
            intent=out.get("intent", ""),
            agent=out.get("agent", ""),
            mode=out.get("mode", ""),
        )
