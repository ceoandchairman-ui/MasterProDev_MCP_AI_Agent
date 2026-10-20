"""Runs tools through one choke point: permission, owner, confirmation, untrusted-content rule, metrics."""

import asyncio
import hashlib
import json
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Dict

import httpx

from mpd_assistant.core.kv import KeyValueStore
from mpd_assistant.core.resilience import CircuitBreaker, CircuitOpen
from mpd_assistant.integrations.context import (
    current_token,
    reset_token,
    reset_untrusted,
    reset_user,
    set_token,
    set_untrusted,
    set_user,
)
from mpd_assistant.memory.short_term.offload import ToolResultStore, digest
from mpd_assistant.observability.metrics import TOOL_CALLS, TOOL_CIRCUIT, TOOL_LATENCY, TOOL_LIMITED, TOOL_RETRIES
from mpd_assistant.privacy.detector import detect
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.registry import Risk, Role, ToolRegistry

ToolBackend = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]

MAX_RESULT_CHARS = 4000


@dataclass
class ToolOutcome:
    tool: str
    status: str  # ok | denied | needs_confirmation | error
    output: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    untrusted: bool = False


@dataclass
class ToolContext:
    agent: Agent
    role: Role
    confirmed_tools: frozenset = frozenset()  # tools the user explicitly confirmed this turn
    untrusted_content_in_context: bool = False  # email bodies, uploads, retrieved text
    session_id: str = ""
    google_access_token: str | None = None  # per-user, sent as a header to Google-backed servers only
    session_row: str = ""
    user_id: str | None = None  # made available to local tools through context, never through arguments


IDEMPOTENCY_TTL_SECONDS = 600
READ_CACHE_TTL_SECONDS = 300
_TOKEN_RE = re.compile(r"<[A-Z_]+_\d+>")


def _digest_args(args: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:32]


def _succeeded(output: Dict[str, Any]) -> bool:
    """Tool servers report application-level failures inside a 200 response; those must never be replayed or cached."""
    return str(output.get("status", "success")) not in ("error", "pending_auth") and "error" not in output


def _shareable(value: Any) -> bool:
    """Safe to keep in a cache shared across people: no privacy tokens and no personal data."""
    text = json.dumps(value, default=str, ensure_ascii=False)
    return not _TOKEN_RE.search(text) and not detect(text)


def _map_strings(value: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _map_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_map_strings(v, fn) for v in value]
    return value


UNTRUSTED_OUTPUT_TOOLS = frozenset({"get_emails", "read_email", "search_knowledge_base"})


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        backend: ToolBackend,
        rehydrate: Callable[[str, str], str] | None = None,
        pseudonymize: Callable[[str, str], str] | None = None,
        audit_sink: Callable[[str, Dict[str, Any], "ToolContext", ToolOutcome, int], None] | None = None,
        kv: KeyValueStore | None = None,
        read_cache: Any = None,
        cache_scope: str = "",
        offload: ToolResultStore | None = None,
    ):
        self._registry = registry
        self._backend = backend
        self._kv = kv  # idempotency for side-effect tools
        self._read_cache = read_cache  # shared cache for tools registered as cacheable reads
        self._cache_scope = cache_scope  # e.g. the corpus version: bumping it makes old entries miss
        self._offload = offload  # keeps large results out of the prompt but re-openable
        self._pseudonymize = pseudonymize  # (session_id, text) -> text with real values replaced by tokens
        self._rehydrate = rehydrate  # (session_id, text) -> text with privacy tokens replaced by real values
        self._audit_sink = audit_sink  # persists every call: (tool, args, ctx, outcome, latency_ms)
        self.audit: deque = deque(maxlen=500)  # recent calls only; the durable record is the sink

    async def run(self, tool: str, args: Dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        spec = self._registry.get(tool)
        if spec is None or not self._registry.is_allowed(tool, ctx.role, ctx.agent):
            return self._record(tool, args, ctx, ToolOutcome(tool, "denied", reason="not_permitted"))
        if spec.inject_user and not ctx.user_id:
            return self._record(tool, args, ctx, ToolOutcome(tool, "denied", reason="identity_required"))
        if spec.needs_confirmation:
            if ctx.untrusted_content_in_context and tool not in ctx.confirmed_tools:
                return self._record(tool, args, ctx, ToolOutcome(tool, "needs_confirmation", reason="side_effect_after_untrusted_content"))
            if tool not in ctx.confirmed_tools:
                return self._record(tool, args, ctx, ToolOutcome(tool, "needs_confirmation", reason="user_confirmation_required"))

        idem_key = None
        if spec.risk is not Risk.READ and self._kv is not None:
            # The same confirmed action, repeated (double "yes", client retry), must not send or create twice.
            idem_key = f"idem-tool:{tool}:{ctx.session_id}:{_digest_args(args)}"
            prior = self._kv.get(idem_key)
            if prior is not None:
                return self._record(tool, args, ctx, ToolOutcome(tool, "ok", prior, reason="duplicate"))
        cache_key = None
        if spec.cacheable and self._read_cache is not None and _shareable(args):
            cache_key = f"toolcache:{self._cache_scope}:{tool}:{_digest_args(args)}"
            cached = await self._read_cache.get(cache_key)
            if cached is not None:
                hit = ToolOutcome(tool, "ok", json.loads(cached), "cache_hit", untrusted=tool in UNTRUSTED_OUTPUT_TOOLS)
                return self._record(tool, args, ctx, hit)

        if spec.limit_per_day and self._kv is not None:
            who = ctx.user_id or ctx.session_id or "anonymous"
            day = time.strftime("%Y%m%d", time.gmtime())
            if self._kv.incr(f"toollimit:{tool}:{who}:{day}", 86400) > spec.limit_per_day:
                TOOL_LIMITED.labels(tool).inc()
                return self._record(tool, args, ctx, ToolOutcome(tool, "denied", reason="daily_limit"))

        started = time.perf_counter()
        try:
            real_args = _map_strings(args, lambda t: self._rehydrate(ctx.session_id, t)) if self._rehydrate else args
            if spec.inject_user:
                real_args = {**real_args, "user_id": ctx.user_id}  # always the verified session's user, whatever the model proposed
            if spec.takes_idempotency_key:
                real_args = {**real_args, "idempotency_key": f"{ctx.session_id}:{_digest_args(args)}"}
            marker = set_token(ctx.google_access_token)
            user_marker = set_user(ctx.user_id)
            taint_marker = set_untrusted(ctx.untrusted_content_in_context)
            try:
                output = await self._backend(tool, real_args)
            finally:
                reset_untrusted(taint_marker)
                reset_user(user_marker)
                reset_token(marker)
            if self._pseudonymize:
                output = _map_strings(output, lambda t: self._pseudonymize(ctx.session_id, t))
            output = self._shrink(tool, output, ctx.session_id)  # after pseudonymizing, so stored copies hold tokens only
            status = "ok"
            reason = ""
            if _succeeded(output):
                if idem_key is not None:
                    self._kv.set(idem_key, output, IDEMPOTENCY_TTL_SECONDS)
                if cache_key is not None and _shareable(output):
                    await self._read_cache.set(cache_key, json.dumps(output, default=str), READ_CACHE_TTL_SECONDS)
        except Exception as exc:
            output, status, reason = {}, "error", type(exc).__name__  # exception text may contain sensitive data
        elapsed = time.perf_counter() - started
        TOOL_LATENCY.labels(tool).observe(elapsed)
        outcome = ToolOutcome(tool, status, output, reason, untrusted=tool in UNTRUSTED_OUTPUT_TOOLS and status == "ok")
        return self._record(tool, args, ctx, outcome, int(elapsed * 1000))

    def _shrink(self, tool: str, output: Dict[str, Any], session_id: str) -> Dict[str, Any]:
        text = str(output)
        if len(text) <= MAX_RESULT_CHARS:
            return output
        if self._offload is not None:
            ref = self._offload.put(session_id, tool, output)
            if ref:
                return {"truncated": True, "preview": digest(output), "ref": ref}
        return {"truncated": True, "preview": text[:MAX_RESULT_CHARS]}

    def open_result(self, session_id: str, ref: str) -> Dict[str, Any] | None:
        """Re-open an offloaded result. Only the conversation that produced it can."""
        return self._offload.get(session_id, ref) if self._offload is not None else None

    def _record(self, tool: str, args: Dict[str, Any], ctx: "ToolContext", outcome: ToolOutcome, latency_ms: int = 0) -> ToolOutcome:
        TOOL_CALLS.labels(outcome.tool if self._registry.get(outcome.tool) else "unknown", outcome.status).inc()
        self.audit.append(outcome)
        if self._audit_sink is not None:
            try:
                self._audit_sink(tool, args, ctx, outcome, latency_ms)
            except Exception:
                pass  # auditing must never break a conversation; the failure shows up as a metric gap, not an outage
        return outcome


TRANSIENT_STATUS = frozenset({408, 429, 502, 503, 504})


def _counts_against_service(exc: BaseException) -> bool:
    """Network trouble and server-side errors say the service is unwell; a 4xx says the request was wrong."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(exc, httpx.HTTPError)


def http_backend(
    routes: Dict[str, tuple[str, str]],
    service_key: str | None,
    client,
    registry: ToolRegistry | None = None,
    *,
    timeout: float = 15.0,
    retries: int = 2,
    max_concurrency: int = 16,
    breaker_threshold: int = 5,
    breaker_reset: float = 30.0,
    base_delay: float = 0.3,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ToolBackend:
    """Backend that calls MCP tool servers over HTTP. routes: registry tool -> (server base URL, server tool name).

    Each service has its own circuit breaker, so a down mail service does not slow calendar calls. Only read-only tools
    are retried (given a registry to tell them apart): repeating a send or a delete could do it twice. At most
    `max_concurrency` calls run at once."""
    breakers: Dict[str, CircuitBreaker] = {}
    slots = asyncio.Semaphore(max(1, max_concurrency))

    async def call(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        route = routes.get(tool)
        if not route:
            raise LookupError("no server for tool")
        base, server_tool = route
        base = base.rstrip("/")
        breaker = breakers.setdefault(base, CircuitBreaker(failure_threshold=breaker_threshold, reset_seconds=breaker_reset))
        try:
            breaker.allow()
        except CircuitOpen:
            TOOL_CIRCUIT.labels(base).inc()
            raise
        headers = {"Authorization": f"Bearer {service_key}"} if service_key else {}
        user_token = current_token()
        if user_token:
            headers["X-Google-Access-Token"] = user_token
        spec = registry.get(tool) if registry is not None else None
        attempts = 1 + (max(0, retries) if spec is not None and spec.risk is Risk.READ else 0)
        for attempt in range(attempts):
            try:
                async with slots:
                    resp = await client.post(f"{base}/call", params={"tool_name": server_tool}, json=args, headers=headers, timeout=timeout)
                resp.raise_for_status()
                result = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                if _counts_against_service(exc):
                    breaker.record_failure()
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                transient = status in TRANSIENT_STATUS if status is not None else isinstance(exc, httpx.TransportError)
                if not transient or attempt == attempts - 1:
                    raise
                TOOL_RETRIES.labels(tool, str(status or "network")).inc()
                await sleep(base_delay * (2**attempt))
                continue
            breaker.record_success()
            return result
        raise RuntimeError("unreachable")  # pragma: no cover

    return call
