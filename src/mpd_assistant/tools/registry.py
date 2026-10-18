"""One registry declares every tool: owner agent, risk, minimum role, caching. Default deny."""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

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


@dataclass(frozen=True)
class ToolSpec:
    name: str
    owner: Agent
    risk: Risk
    min_role: Role
    cacheable: bool = False

    @property
    def needs_confirmation(self) -> bool:
        return self.risk is not Risk.READ


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Duplicate tool: {spec.name}")
        if spec.cacheable and spec.risk is not Risk.READ:
            raise ValueError("Only read tools may be cacheable")
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def is_allowed(self, name: str, role: Role, agent: Optional[Agent] = None) -> bool:
        spec = self._tools.get(name)
        if spec is None:
            return False
        if agent is not None and spec.owner is not agent:
            return False
        return _RANK[role] >= _RANK[spec.min_role]

    def for_agent(self, agent: Agent, role: Role) -> List[ToolSpec]:
        return [s for s in self._tools.values() if self.is_allowed(s.name, role, agent)]


def default_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(ToolSpec("search_knowledge_base", Agent.CONCIERGE, Risk.READ, Role.VISITOR, cacheable=True))
    r.register(ToolSpec("get_calendar_events", Agent.COMMS_SCHEDULING, Risk.READ, Role.VERIFIED))
    r.register(ToolSpec("create_calendar_event", Agent.COMMS_SCHEDULING, Risk.WRITE, Role.VERIFIED))
    r.register(ToolSpec("delete_calendar_event", Agent.COMMS_SCHEDULING, Risk.DESTRUCTIVE, Role.STAFF))
    r.register(ToolSpec("get_emails", Agent.COMMS_SCHEDULING, Risk.READ, Role.STAFF))
    r.register(ToolSpec("read_email", Agent.COMMS_SCHEDULING, Risk.READ, Role.STAFF))
    r.register(ToolSpec("send_email", Agent.COMMS_SCHEDULING, Risk.WRITE, Role.VERIFIED))
    return r
