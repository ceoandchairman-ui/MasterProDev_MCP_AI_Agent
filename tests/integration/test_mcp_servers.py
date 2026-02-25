"""MCP Server tests"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from mcp_servers.calendar_server.main import calendar_server
from mcp_servers.gmail_server.main import gmail_server


# ── Calendar mock helpers ───────────────────────────────────────────────────

def _fake_calendar_event(event_id="evt_001", title="Test Meeting"):
    return {
        "id": event_id,
        "summary": title,
        "description": "Unit test event",
        "start": {"dateTime": "2026-02-24T10:00:00Z"},
        "end":   {"dateTime": "2026-02-24T11:00:00Z"},
        "location": None,
        "attendees": [],
        "htmlLink": f"https://calendar.google.com/event?eid={event_id}",
    }


def _make_calendar_service(events=None):
    """Build a MagicMock that mimics googleapiclient calendar service calls."""
    events = events or [_fake_calendar_event()]
    svc = MagicMock()
    # events().list().execute()
    svc.events().list.return_value.execute.return_value = {"items": events}
    # events().insert().execute()
    svc.events().insert.return_value.execute.return_value = _fake_calendar_event("created_01", "Test Meeting")
    # events().delete().execute()
    svc.events().delete.return_value.execute.return_value = None
    return svc


# ── Gmail mock helpers ──────────────────────────────────────────────────────

def _make_gmail_service(messages=None):
    """Build a MagicMock that mimics googleapiclient gmail service calls."""
    msg_stubs = messages or [{"id": "msg_001"}, {"id": "msg_002"}]
    svc = MagicMock()

    # users().messages().list().execute()
    svc.users().messages().list.return_value.execute.return_value = {"messages": msg_stubs}

    # users().messages().get().execute() — returns metadata
    def _msg_get(**_kwargs):
        m = MagicMock()
        m.execute.return_value = {
            "id": "msg_001",
            "payload": {
                "headers": [
                    {"name": "From",    "value": "sender@example.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "Date",    "value": "Mon, 24 Feb 2026 10:00:00 +0000"},
                ]
            }
        }
        return m

    svc.users().messages().get.side_effect = _msg_get

    # users().messages().send().execute()
    svc.users().messages().send.return_value.execute.return_value = {"id": "sent_msg_001"}
    return svc


# ── Calendar tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_get_events():
    """Test getting calendar events — mocks OAuth service layer."""
    mock_svc = _make_calendar_service()
    with patch.object(calendar_server, "_get_calendar_service", new=AsyncMock(return_value=mock_svc)):
        result = await calendar_server.execute_tool("get_events", {"days": 7})
    assert result["status"] == "success"
    assert "events" in result
    assert isinstance(result["events"], list)
    assert result["events"][0]["title"] == "Test Meeting"


@pytest.mark.asyncio
async def test_calendar_create_event():
    """Test creating a calendar event — mocks OAuth service layer."""
    mock_svc = _make_calendar_service()
    with patch.object(calendar_server, "_get_calendar_service", new=AsyncMock(return_value=mock_svc)):
        result = await calendar_server.execute_tool("create_event", {
            "title": "Test Meeting",
            "start_time": "2026-02-24T10:00:00",
            "end_time": "2026-02-24T11:00:00",
        })
    assert result["status"] == "success"
    assert "event" in result
    assert result["event"]["title"] == "Test Meeting"


# ── Gmail tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gmail_get_emails():
    """Test fetching emails — mocks OAuth service layer."""
    mock_svc = _make_gmail_service()
    with patch.object(gmail_server, "_get_gmail_service", new=AsyncMock(return_value=mock_svc)):
        result = await gmail_server.execute_tool("get_emails", {"limit": 5})
    assert result["status"] == "success"
    assert "emails" in result
    assert isinstance(result["emails"], list)


@pytest.mark.asyncio
async def test_gmail_send_email():
    """Test sending an email — mocks OAuth service layer."""
    mock_svc = _make_gmail_service()
    with patch.object(gmail_server, "_get_gmail_service", new=AsyncMock(return_value=mock_svc)):
        result = await gmail_server.execute_tool("send_email", {
            "to": "recipient@example.com",
            "subject": "Test Email",
            "body": "This is a test email",
        })
    assert result["status"] == "success"
    assert "message_id" in result


def test_calendar_tools():
    """Test calendar tools list"""
    tools = calendar_server.get_available_tools()
    assert len(tools) == 3
    tool_names = [t["name"] for t in tools]
    assert "get_events" in tool_names
    assert "create_event" in tool_names
    assert "delete_event" in tool_names


def test_gmail_tools():
    """Test Gmail tools list"""
    tools = gmail_server.get_available_tools()
    assert len(tools) == 3
    tool_names = [t["name"] for t in tools]
    assert "get_emails" in tool_names
    assert "send_email" in tool_names
    assert "read_email" in tool_names
