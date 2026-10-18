"""API-boundary service: pseudonymize on the way in, restore values only in the reply to this user.

The graph, its checkpoints and every model call only ever see tokens such as <EMAIL_1>.
Optional collaborators (cache, memory, escalations, summaries) are wired in by the application factory.
"""

import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from mpd_assistant.cache.keys import build_key, may_cache
from mpd_assistant.cache.store import DEFAULT_TTL_SECONDS, ResponseCache
from mpd_assistant.evaluation.online.rules import Verdict, evaluate_response
from mpd_assistant.observability.metrics import record_turn
from mpd_assistant.privacy.vault import PiiVault
from mpd_assistant.responses.engine import render
from mpd_assistant.routing.intents import Mode
from mpd_assistant.routing.router import route


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
    cache_hit: bool = False


@dataclass
class CacheSettings:
    tenant: str = "default"
    prompt_version: str = "v1"
    corpus_version: str = "1"


class ChatService:
    def __init__(
        self,
        graph: Any,
        vault: PiiVault,
        *,
        cache: Optional[ResponseCache] = None,
        cache_settings: Optional[CacheSettings] = None,
        extras: Optional[Callable[..., Any]] = None,
    ):
        self._graph = graph
        self._vault = vault
        self._cache = cache
        self._cache_settings = cache_settings or CacheSettings()
        self._extras = extras  # reserved for collaborators wired in later steps

    def _cache_key(self, decision, safe_text: str, user_id: Optional[str]) -> Optional[str]:
        if self._cache is None or decision.requires_identity or decision.mode is Mode.ESCALATE:
            return None
        if decision.intent.value not in DEFAULT_TTL_SECONDS:
            return None
        s = self._cache_settings
        return build_key(
            tenant=s.tenant,
            locale=decision.language,
            mode=decision.mode,
            agent=decision.agent.value,
            query=safe_text,
            prompt_version=s.prompt_version,
            corpus_version=s.corpus_version,
        )

    async def chat(
        self,
        session_id: str,
        raw_text: str,
        verified: bool = False,
        user_id: str | None = None,
    ) -> ChatResult:
        started = time.perf_counter()
        safe_text = self._vault.tokenize(session_id, raw_text)

        decision = route(safe_text, verified=verified)
        key = self._cache_key(decision, safe_text, user_id)
        if key is not None:
            cached = await self._cache.get(key)
            if cached is not None:
                record_turn(
                    agent=decision.agent.value,
                    mode=decision.mode.value,
                    intent=decision.intent.value,
                    seconds=time.perf_counter() - started,
                    verdict="pass",
                    escalated=False,
                )
                return ChatResult(
                    cached,
                    False,
                    None,
                    [],
                    safe_user_text=safe_text,
                    intent=decision.intent.value,
                    agent=decision.agent.value,
                    mode=decision.mode.value,
                    cache_hit=True,
                )

        out = await self._graph.ainvoke(
            {"messages": [{"role": "user", "content": safe_text}], "session_id": session_id, "verified": verified, "user_id": user_id},
            config={"configurable": {"thread_id": session_id}},
        )
        graph_reply = out.get("response") or ""
        reply = self._vault.detokenize(session_id, graph_reply)
        final = evaluate_response(reply, language=out.get("language", "en"), allowed_pii=self._vault.known_values(session_id))
        if final.verdict is not Verdict.PASS:
            reply = render("temporary_error", out.get("language", "en"))
        reasons = list(out.get("eval_reasons", [])) + final.reasons

        if (
            key is not None
            and final.verdict is Verdict.PASS
            and out.get("eval_verdict") == "pass"
            and may_cache(
                intent=decision.intent,
                query=safe_text,
                response=graph_reply,
                evaluator_passed=True,
                used_side_effect_tool=False,
            )
        ):
            await self._cache.set(key, graph_reply, DEFAULT_TTL_SECONDS[decision.intent.value])

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
