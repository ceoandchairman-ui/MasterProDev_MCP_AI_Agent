"""One registry declares every tool: owner agent, risk, minimum role, caching, and the arguments it accepts. Default deny."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Tuple

from mpd_assistant.routing.intents import Agent


class Role(str, Enum):
    VISITOR = "visitor"
    VERIFIED = "verified"
    STAFF = "staff"


_RANK = {Role.VISITOR: 0, Role.VERIFIED: 1, Role.STAFF: 2}


class Risk(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
_PRIVACY_TOKEN = re.compile(r"^<[A-Z_]+_\d+>$")  # a pseudonymized value such as <EMAIL_1>; the real value is restored at the boundary
TYPES = ("str", "int", "bool", "list", "datetime", "email", "emails")


@dataclass(frozen=True)
class Param:
    name: str
    type: str = "str"
    required: bool = False
    description: str = ""
    max_len: int = 4000

    def __post_init__(self) -> None:
        if self.type not in TYPES:
            raise ValueError(f"Unknown parameter type: {self.type}")

    def problem(self, value: Any) -> str | None:
        """None when the value is acceptable, else a short reason."""
        if self.type == "int":
            return None if isinstance(value, int) and not isinstance(value, bool) else "must be a whole number"
        if self.type == "bool":
            return None if isinstance(value, bool) else "must be true or false"
        if self.type == "list":
            return None if isinstance(value, list) else "must be a list"
        if self.type == "emails":
            items = value.split(",") if isinstance(value, str) else value
            if not isinstance(items, list) or not items or not all(isinstance(i, str) and i.strip() for i in items):
                return "must be one or more email addresses"
            return None if all(_address_ok(i) for i in items) else "contains an invalid address"
        if not isinstance(value, str) or not value.strip():
            return "must be text"
        if len(value) > self.max_len:
            return "is too long"
        if self.type == "email" and not _address_ok(value):
            return "must be an email address"
        if self.type == "datetime":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return "must be an ISO 8601 date and time, for example 2026-11-02T14:00:00"
        return None

    def signature(self) -> str:
        return f"{self.name}{'' if self.required else '?'}: {self.type}"


def _address_ok(value: Any) -> bool:
    return isinstance(value, str) and bool(_EMAIL.match(value.strip()) or _PRIVACY_TOKEN.match(value.strip()))


@dataclass(frozen=True)
class ToolSpec:
    name: str
    owner: Agent
    risk: Risk
    min_role: Role
    cacheable: bool = False
    shared_with: frozenset = frozenset()  # other agents allowed to use the tool, in addition to the owner
    description: str = ""
    params: Tuple[Param, ...] = ()  # empty means the tool takes no arguments the model controls
    inject_user: bool = False  # the executor sets `user_id` from the verified session; the model can never choose it

    @property
    def needs_confirmation(self) -> bool:
        return self.risk is not Risk.READ

    @property
    def takes_idempotency_key(self) -> bool:
        return any(p.name == "idempotency_key" for p in self.params)

    def signature(self) -> str:
        shown = ", ".join(p.signature() for p in self.params if p.name != "idempotency_key")
        return f"{self.name}({shown})"


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Duplicate tool: {spec.name}")
        if spec.cacheable and spec.risk is not Risk.READ:
            raise ValueError("Only read tools may be cacheable")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def is_allowed(self, name: str, role: Role, agent: Agent | None = None) -> bool:
        spec = self._tools.get(name)
        if spec is None:
            return False
        if agent is not None and spec.owner is not agent and agent not in spec.shared_with:
            return False
        return _RANK[role] >= _RANK[spec.min_role]

    def for_agent(self, agent: Agent, role: Role) -> List[ToolSpec]:
        return [s for s in self._tools.values() if self.is_allowed(s.name, role, agent)]

    def describe(self, agent: Agent, role: Role) -> str:
        """The tool list a planner prompt shows: one line per tool with its arguments and purpose."""
        lines = []
        for spec in self.for_agent(agent, role):
            note = " [needs user confirmation]" if spec.needs_confirmation else ""
            lines.append(f"- {spec.signature()}: {spec.description}{note}")
        return "\n".join(lines)

    def validate_args(self, name: str, args: Any) -> List[str]:
        """Problems with the arguments a model proposed, empty when fine. Unknown keys are reported, never passed on."""
        spec = self._tools.get(name)
        if spec is None:
            return ["unknown tool"]
        if not isinstance(args, dict):
            return ["arguments must be an object"]
        known = {p.name: p for p in spec.params}
        problems = [f"{key} is not an argument of {name}" for key in args if key not in known]
        for param in spec.params:
            if param.name == "idempotency_key" or (spec.inject_user and param.name == "user_id"):
                continue  # supplied by the executor, not the model
            if args.get(param.name) in (None, ""):
                if param.required:
                    problems.append(f"{param.name} is required")
                continue
            reason = param.problem(args[param.name])
            if reason:
                problems.append(f"{param.name} {reason}")
        return problems

    def clean_args(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Only declared arguments, with the executor-supplied ones removed."""
        spec = self._tools.get(name)
        if spec is None:
            return {}
        names = {p.name for p in spec.params if p.name != "idempotency_key" and not (spec.inject_user and p.name == "user_id")}
        return {k: v for k, v in args.items() if k in names}


def default_registry() -> ToolRegistry:
    r = ToolRegistry()
    comms = Agent.COMMS_SCHEDULING
    r.register(ToolSpec("search_knowledge_base", Agent.CONCIERGE, Risk.READ, Role.VISITOR, cacheable=True, description="Search the company knowledge base", params=(Param("query", "str", True, "what to look for"),)))

    # Calendar
    tz = Param("time_zone", "str", False, "IANA zone such as America/Toronto", 64)
    r.register(ToolSpec("get_calendar_events", comms, Risk.READ, Role.VERIFIED, description="List upcoming calendar events", params=(Param("days", "int", False, "days ahead, 1 to 30"), tz)))
    r.register(
        ToolSpec(
            "find_free_slots", comms, Risk.READ, Role.VERIFIED, description="Find open time slots inside working hours",
            params=(Param("start", "datetime", False, "window start"), Param("end", "datetime", False, "window end"), Param("duration_min", "int", False, "length in minutes, 15 to 480"), tz),
        )
    )
    r.register(
        ToolSpec(
            "create_calendar_event", comms, Risk.WRITE, Role.VERIFIED, description="Create a calendar event",
            params=(
                Param("title", "str", True, "event title", 200), Param("start_time", "datetime", True), Param("end_time", "datetime", True), tz,
                Param("description", "str", False), Param("attendees", "emails", False, "guest email addresses"), Param("idempotency_key", "str"),
            ),
        )
    )
    r.register(
        ToolSpec(
            "reschedule_calendar_event", comms, Risk.WRITE, Role.VERIFIED, description="Move an existing event to a new time",
            params=(Param("event_id", "str", True, "id from get_calendar_events", 200), Param("start_time", "datetime", True), Param("end_time", "datetime", True), tz),
        )
    )
    r.register(ToolSpec("delete_calendar_event", comms, Risk.DESTRUCTIVE, Role.STAFF, description="Delete an event", params=(Param("event_id", "str", True, "id from get_calendar_events", 200),)))

    # Email
    r.register(ToolSpec("get_emails", comms, Risk.READ, Role.STAFF, description="List recent emails", params=(Param("limit", "int", False), Param("query", "str", False, "Gmail search text", 200))))
    r.register(ToolSpec("read_email", comms, Risk.READ, Role.STAFF, description="Read one email in full", params=(Param("email_id", "str", True, "id from get_emails", 200),)))
    mail = (Param("to", "emails", True, "recipient addresses"), Param("subject", "str", True, "subject line", 200), Param("body", "str", True, "message text", 20000), Param("cc", "emails", False))
    r.register(ToolSpec("create_email_draft", comms, Risk.WRITE, Role.VERIFIED, description="Save an email as a draft without sending", params=mail))
    r.register(ToolSpec("send_email", comms, Risk.WRITE, Role.VERIFIED, description="Send an email", params=mail + (Param("idempotency_key", "str"),)))

    # Company data (read-only, scoped to the signed-in user by the executor)
    r.register(ToolSpec("get_lead_stage", Agent.LEAD_CONVERSION, Risk.READ, Role.VERIFIED, description="The signed-in user's funnel stage, timeline and budget", params=(Param("user_id", "str"),), inject_user=True))
    r.register(
        ToolSpec(
            "list_my_quotes", Agent.QUOTE, Risk.READ, Role.VERIFIED, shared_with=frozenset({Agent.LEAD_CONVERSION}),
            description="The signed-in user's quotes: reference, status, total, expiry", params=(Param("user_id", "str"),), inject_user=True,
        )
    )
    r.register(
        ToolSpec(
            "get_quote_details", Agent.QUOTE, Risk.READ, Role.VERIFIED, description="Line items and status of one of the user's quotes",
            params=(Param("user_id", "str"), Param("quote_ref", "str", True, "8-character quote reference", 8)), inject_user=True,
        )
    )
    r.register(ToolSpec("get_customer_profile", Agent.LEAD_CONVERSION, Risk.READ, Role.VERIFIED, shared_with=frozenset({Agent.QUOTE}), description="Company and engagement summary for the signed-in user", params=(Param("user_id", "str"),), inject_user=True))

    # Memory: any agent that talks to a verified user may look things up; only the two conversational agents may save.
    searchers = frozenset({Agent.LEAD_CONVERSION, Agent.SOLUTION_ARCHITECT, Agent.QUOTE, Agent.COMMS_SCHEDULING})
    r.register(ToolSpec("memory_search", Agent.CONCIERGE, Risk.READ, Role.VERIFIED, shared_with=searchers, description="Search what is remembered about the user", params=(Param("query", "str", True),)))
    r.register(ToolSpec("memory_save", Agent.LEAD_CONVERSION, Risk.WRITE, Role.VERIFIED, shared_with=frozenset({Agent.CONCIERGE}), description="Remember a fact the user stated", params=(Param("text", "str", True, "the fact", 500), Param("kind", "str", False, "fact or preference", 20), Param("slot", "str", False, "key that a newer value replaces, such as preferred_language", 60))))
    return r
