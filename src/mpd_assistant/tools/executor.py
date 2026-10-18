"""Runs tools through one choke point: permission, owner, confirmation, untrusted-content rule, metrics."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mpd_assistant.observability.metrics import TOOL_CALLS, TOOL_LATENCY
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.registry import Role, ToolRegistry

ToolBackend = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]

MAX_RESULT_CHARS = 4000


@dataclass
class ToolOutcome:
    tool: str
    status: str  # ok | denied | needs_confirmation | error
    output: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class ToolContext:
    agent: Agent
    role: Role
    confirmed_tools: frozenset = frozenset()  # tools the user explicitly confirmed this turn
    untrusted_content_in_context: bool = False  # email bodies, uploads, retrieved text
    session_id: str = ""


def _truncate(output: Dict[str, Any]) -> Dict[str, Any]:
    text = str(output)
    if len(text) <= MAX_RESULT_CHARS:
        return output
    return {"truncated": True, "preview": text[:MAX_RESULT_CHARS]}


def _map_strings(value: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _map_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_map_strings(v, fn) for v in value]
    return value


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, backend: ToolBackend, rehydrate: Callable[[str, str], str] | None = None,
                 pseudonymize: Callable[[str, str], str] | None = None):
        self._registry = registry
        self._backend = backend
        self._pseudonymize = pseudonymize  # (session_id, text) -> text with real values replaced by tokens
        self._rehydrate = rehydrate  # (session_id, text) -> text with privacy tokens replaced by real values
        self.audit: List[ToolOutcome] = []

    async def run(self, tool: str, args: Dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        spec = self._registry.get(tool)
        if spec is None or not self._registry.is_allowed(tool, ctx.role, ctx.agent):
            return self._record(ToolOutcome(tool, "denied", reason="not_permitted"))
        if spec.needs_confirmation:
            if ctx.untrusted_content_in_context and tool not in ctx.confirmed_tools:
                return self._record(ToolOutcome(tool, "needs_confirmation", reason="side_effect_after_untrusted_content"))
            if tool not in ctx.confirmed_tools:
                return self._record(ToolOutcome(tool, "needs_confirmation", reason="user_confirmation_required"))

        started = time.perf_counter()
        try:
            real_args = _map_strings(args, lambda t: self._rehydrate(ctx.session_id, t)) if self._rehydrate else args
            output = _truncate(await self._backend(tool, real_args))
            if self._pseudonymize:
                output = _map_strings(output, lambda t: self._pseudonymize(ctx.session_id, t))
            status = "ok"
            reason = ""
        except Exception as exc:
            output, status, reason = {}, "error", type(exc).__name__  # exception text may contain sensitive data
        TOOL_LATENCY.labels(tool).observe(time.perf_counter() - started)
        return self._record(ToolOutcome(tool, status, output, reason))

    def _record(self, outcome: ToolOutcome) -> ToolOutcome:
        TOOL_CALLS.labels(outcome.tool if self._registry.get(outcome.tool) else "unknown", outcome.status).inc()
        self.audit.append(outcome)
        return outcome


def http_backend(routes: Dict[str, tuple[str, str]], service_key: Optional[str], client) -> ToolBackend:
    """Backend that calls MCP tool servers over HTTP. routes: registry tool -> (server base URL, server tool name)."""

    async def call(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        route = routes.get(tool)
        if not route:
            raise LookupError("no server for tool")
        base, server_tool = route
        headers = {"Authorization": f"Bearer {service_key}"} if service_key else {}
        resp = await client.post(f"{base.rstrip('/')}/call", params={"tool_name": server_tool}, json=args, headers=headers, timeout=15.0)
        resp.raise_for_status()
        return resp.json()

    return call
