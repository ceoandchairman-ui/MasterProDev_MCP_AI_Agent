"""API-boundary service: pseudonymize on the way in, restore values only in the reply to this user.

The graph, its checkpoints and every model call only ever see tokens such as <EMAIL_1>.
Optional collaborators (cache, memory, escalations, summaries) are wired in by the application factory.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, List

from langgraph.errors import GraphRecursionError

from mpd_assistant.cache.keys import build_key, may_cache
from mpd_assistant.cache.store import DEFAULT_TTL_SECONDS, ResponseCache
from mpd_assistant.core.llm.budget import reset_scope, set_scope
from mpd_assistant.core.resilience import infrastructure_failure
from mpd_assistant.evaluation.online.rules import Verdict, evaluate_response
from mpd_assistant.observability.metrics import DEGRADED, record_turn
from mpd_assistant.privacy.detector import detect
from mpd_assistant.privacy.vault import PiiVault
from mpd_assistant.responses.engine import render
from mpd_assistant.routing.intents import Agent, Intent, Mode
from mpd_assistant.routing.router import detect_language, route

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"<[A-Z_]+_\d+>")
SEMANTIC_INTENTS = frozenset({Intent.FAQ, Intent.KNOWLEDGE_QUESTION})


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
        cache: ResponseCache | None = None,
        cache_settings: CacheSettings | None = None,
        memory: Any = None,
        escalations: Any = None,
        summarizer: Any = None,
        budget: Any = None,
        semantic: Any = None,
        entities: Any = None,
        topics: Any = None,
        uploads: Any = None,
        patterns: Any = None,
        episodes: Any = None,
        turn_timeout: float | None = None,
        recursion_limit: int = 30,
    ):
        self._turn_timeout, self._recursion_limit = turn_timeout, recursion_limit
        self._entities, self._topics, self._uploads, self._patterns, self._episodes = entities, topics, uploads, patterns, episodes
        self._semantic = semantic
        self._graph = graph
        self._vault = vault
        self._cache = cache
        self._cache_settings = cache_settings or CacheSettings()
        self._memory = memory
        self._escalations = escalations
        self._summarizer = summarizer
        self._budget = budget

    def _cache_key(self, decision, safe_text: str, user_id: str | None) -> str | None:
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

    def _semantic_scope(self, decision, safe_text: str) -> str | None:
        """Semantic reuse is limited to shareable knowledge questions with no personal data in them."""
        if self._semantic is None or decision.intent not in SEMANTIC_INTENTS or decision.requires_identity:
            return None
        if _TOKEN_RE.search(safe_text) or detect(safe_text):
            return None
        s = self._cache_settings
        return self._semantic.scope(s.tenant, decision.language, decision.agent.value, s.prompt_version, s.corpus_version)

    def _turn_notes(self, thread_id: str, decision, safe_text: str) -> str:
        """What 'that email' or 'the meeting' refers to, and whether the user switched or resumed a topic."""
        parts: List[str] = []
        if self._entities is not None:
            parts.append(self._entities.context_note(thread_id, safe_text))
        if self._topics is not None:
            task_open = decision.agent not in (Agent.CONCIERGE, Agent.ESCALATION)
            shift = self._topics.observe(thread_id, decision.intent.value, safe_text, task_open=task_open)
            if shift.resume and shift.parked:
                parts.append(f"The user is resuming an earlier topic: {shift.parked.summary}. ")
            elif shift.parked:
                parts.append(f"The user changed topic. The earlier unfinished topic was: {shift.parked.summary}. ")
        return "".join(p for p in parts if p).strip()

    async def _escalate_loop(self, session_id: str, session_row: str | None, safe_text: str, decision) -> "ChatResult":
        reference = None
        if self._escalations is not None:
            state = {"session_id": session_id, "session_row": session_row, "messages": [{"role": "user", "content": safe_text}], "language": decision.language}
            try:
                reference = await self._escalations.hook(state, "loop_limit")
            except Exception:
                logger.exception("escalation after a loop-limit stop failed")
        reply = render("escalation_notice", decision.language, {"reference": reference}) if reference else render("temporary_error", decision.language)
        return ChatResult(
            reply, bool(reference), reference, ["loop_limit"], safe_user_text=safe_text,
            intent=decision.intent.value, agent=decision.agent.value, mode=decision.mode.value,
        )

    async def end_conversation(self, thread_id: str, user_id: str | None, outcome: str = "no_outcome") -> None:
        """Called when a conversation is closed: keeps a short episode (with consent) and clears per-thread working state."""
        if self._episodes is not None and user_id:
            try:
                await self._episodes.record(user_id, thread_id, outcome)
            except Exception:
                logger.exception("episode record failed")  # losing an episode must never break closing a conversation
        for tracker in (self._entities, self._topics):
            if tracker is not None:
                tracker.clear(thread_id)

    async def chat(
        self,
        session_id: str,
        raw_text: str,
        verified: bool = False,
        user_id: str | None = None,
        session_row: str | None = None,
    ) -> ChatResult:
        """One turn. A connection-level failure of Postgres or Redis becomes a polite 'please retry' reply and a metric;
        anything else (a real bug) still raises."""
        try:
            return await self._chat(session_id, raw_text, verified, user_id, session_row)
        except Exception as exc:
            dependency = infrastructure_failure(exc)
            if dependency is None:
                raise
            logger.error("dependency failure (%s) during a turn; serving a degraded reply: %s", dependency, type(exc).__name__)
            DEGRADED.labels(dependency).inc()
            return ChatResult(
                render("temporary_error", detect_language(raw_text)),
                False,
                None,
                [f"degraded_{dependency}"],
            )

    async def _chat(
        self,
        session_id: str,
        raw_text: str,
        verified: bool = False,
        user_id: str | None = None,
        session_row: str | None = None,
    ) -> ChatResult:
        started = time.perf_counter()
        safe_text = self._vault.tokenize(session_id, raw_text)

        if self._escalations is not None and session_row and await asyncio.to_thread(self._escalations.is_paused, session_row):
            # A person has been asked to take over: the assistant stays quiet instead of talking over them.
            reference = await asyncio.to_thread(self._escalations.open_reference, session_row)
            return ChatResult(
                render("escalation_paused", route(safe_text).language, {"reference": reference or ""}),
                True,
                reference,
                [],
                safe_user_text=safe_text,
                intent="escalated",
                agent="escalation",
                mode="escalate",
            )

        decision = route(safe_text, verified=verified)

        if self._budget is not None and decision.mode not in (Mode.TEMPLATED, Mode.ESCALATE):  # asking for a person never needs the model
            spent = self._budget.exhausted(session_id)
            if spent:
                return ChatResult(
                    render("budget_exceeded" if spent == "session" else "service_busy", decision.language),
                    False,
                    None,
                    ["budget_" + spent],
                    safe_user_text=safe_text,
                    intent=decision.intent.value,
                    agent=decision.agent.value,
                    mode=decision.mode.value,
                )
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

        semantic_scope = self._semantic_scope(decision, safe_text)
        if semantic_scope is not None:
            similar = await self._semantic.lookup(semantic_scope, safe_text)
            if similar is not None:
                record_turn(
                    agent=decision.agent.value,
                    mode=decision.mode.value,
                    intent=decision.intent.value,
                    seconds=time.perf_counter() - started,
                    verdict="pass",
                    escalated=False,
                )
                return ChatResult(
                    similar,
                    False,
                    None,
                    [],
                    safe_user_text=safe_text,
                    intent=decision.intent.value,
                    agent=decision.agent.value,
                    mode=decision.mode.value,
                    cache_hit=True,
                )

        memory_context = await self._memory.before(user_id, safe_text) if self._memory else ""
        context_notes = self._turn_notes(session_id, decision, safe_text)
        attachment_context = self._uploads.context_for(session_id) if self._uploads is not None else ""
        style_examples = ""
        if self._patterns is not None and decision.mode in (Mode.GENERATED, Mode.REASONED):
            style_examples = self._patterns.few_shot_block(decision.intent.value, decision.language)
        marker = set_scope(session_id)  # every model call in this turn is charged to this conversation
        try:
            run = self._graph.ainvoke(
                {
                    "messages": [{"role": "user", "content": safe_text}],
                    "session_id": session_id,
                    "verified": verified,
                    "user_id": user_id,
                    "steps": 0,  # the checkpoint keeps state between turns; the step guard is per turn
                    "escalated": False,
                    "reference": None,
                    "current_task": None,
                    "task_queue": [],
                    "partials": [],
                    "memory_context": memory_context,
                    "thread_summary": self._summarizer.context_for(session_id) if self._summarizer else "",
                    "session_row": session_row,
                    "context_notes": context_notes,
                    "attachment_context": attachment_context,
                    "style_examples": style_examples,
                },
                config={"configurable": {"thread_id": session_id}, "recursion_limit": self._recursion_limit},
            )
            out = await (asyncio.wait_for(run, self._turn_timeout) if self._turn_timeout else run)
        except TimeoutError:
            # The turn ran out of time (a slow model or tool). The user gets a retry message instead of a hung request.
            DEGRADED.labels("turn_timeout").inc()
            logger.error("turn exceeded %.0f seconds and was cancelled", self._turn_timeout or 0)
            return ChatResult(
                render("temporary_error", decision.language), False, None, ["turn_timeout"], safe_user_text=safe_text,
                intent=decision.intent.value, agent=decision.agent.value, mode=decision.mode.value,
            )
        except GraphRecursionError:
            # The graph kept looping. A person takes over rather than the user seeing a server error.
            DEGRADED.labels("loop_limit").inc()
            logger.error("conversation graph hit its recursion limit (%d)", self._recursion_limit)
            return await self._escalate_loop(session_id, session_row, safe_text, decision)
        finally:
            reset_scope(marker)
        graph_reply = out.get("response") or ""
        reply = self._vault.detokenize(session_id, graph_reply)
        final = evaluate_response(reply, language=out.get("language", "en"), allowed_pii=self._vault.known_values(session_id))
        if final.verdict is not Verdict.PASS:
            reply = render("temporary_error", out.get("language", "en"))
        reasons = list(out.get("eval_reasons", [])) + final.reasons

        if self._summarizer is not None:
            snapshot = await self._graph.aget_state({"configurable": {"thread_id": session_id}})
            await self._summarizer.maybe_update(session_id, list(snapshot.values.get("messages", [])))

        if self._memory:
            await self._memory.after(user_id, safe_text, allow=final.verdict is Verdict.PASS and decision.mode is not Mode.TEMPLATED)

        cacheable = (
            final.verdict is Verdict.PASS
            and out.get("eval_verdict") == "pass"
            and may_cache(
                intent=decision.intent,
                query=safe_text,
                response=graph_reply,
                evaluator_passed=True,
                used_side_effect_tool=False,
            )
        )
        if cacheable and key is not None:
            await self._cache.set(key, graph_reply, DEFAULT_TTL_SECONDS[decision.intent.value])
        if self._patterns is not None and final.verdict is Verdict.PASS and out.get("eval_verdict") == "pass" and decision.mode is Mode.REASONED and not out.get("escalated"):
            try:
                self._patterns.propose(decision.intent.value, decision.language, safe_text, graph_reply)  # staff approve before it is ever used
            except Exception:
                logger.exception("pattern proposal failed")
        if out.get("escalated") and self._episodes is not None and user_id:
            await self.end_conversation(session_id, user_id, "escalated")
        if cacheable and semantic_scope is not None:
            await self._semantic.store(semantic_scope, safe_text, graph_reply, DEFAULT_TTL_SECONDS[decision.intent.value])

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
