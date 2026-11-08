"""Role-based tool permissions, enforced in code before any tool runs."""

from typing import Iterable, List

GUEST = "guest"
STAFF = "staff"

# Default deny: a tool that is not listed here is unavailable to every role.
GUEST_TOOLS = frozenset({"search_knowledge_base"})
STAFF_TOOLS = GUEST_TOOLS | frozenset(
    {
        "get_calendar_events",
        "create_calendar_event",
        "delete_calendar_event",
        "get_emails",
        "read_email",
        "send_email",
    }
)

_ROLE_TOOLS = {GUEST: GUEST_TOOLS, STAFF: STAFF_TOOLS}


def role_for_user(user_id: str | None) -> str:
    return GUEST if not user_id or user_id == "guest" else STAFF


def is_tool_allowed(tool_name: str, role: str) -> bool:
    return tool_name in _ROLE_TOOLS.get(role, frozenset())


def filter_tools(tools: Iterable, role: str) -> List:
    return [t for t in tools if is_tool_allowed(getattr(t, "name", ""), role)]
