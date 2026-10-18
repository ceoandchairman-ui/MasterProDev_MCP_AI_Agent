from types import SimpleNamespace

from mcp_host.tool_policy import GUEST, STAFF, filter_tools, is_tool_allowed, role_for_user

DESTRUCTIVE_OR_PRIVATE = ["send_email", "read_email", "get_emails", "delete_calendar_event", "create_calendar_event", "get_calendar_events"]


def test_role_mapping():
    assert role_for_user(None) == GUEST
    assert role_for_user("guest") == GUEST
    assert role_for_user("admin@example.com") == STAFF


def test_guest_can_only_search_knowledge():
    assert is_tool_allowed("search_knowledge_base", GUEST)
    for tool in DESTRUCTIVE_OR_PRIVATE:
        assert not is_tool_allowed(tool, GUEST), tool


def test_staff_gets_all_known_tools():
    for tool in DESTRUCTIVE_OR_PRIVATE + ["search_knowledge_base"]:
        assert is_tool_allowed(tool, STAFF), tool


def test_unknown_tool_and_role_are_denied():
    assert not is_tool_allowed("drop_database", STAFF)
    assert not is_tool_allowed("search_knowledge_base", "nobody")


def test_filter_tools():
    tools = [SimpleNamespace(name=n) for n in ["search_knowledge_base", "send_email"]]
    assert [t.name for t in filter_tools(tools, GUEST)] == ["search_knowledge_base"]
