"""MCP Server tests"""

import pytest
import asyncio
from mcp_servers.calendar_server.main import calendar_server
from mcp_servers.gmail_server.main import gmail_server


@pytest.mark.asyncio
async def test_calendar_get_events():
    """Test getting calendar events"""
    result = await calendar_server.execute_tool("get_events", {"days": 7})
    assert result["status"] == "success"
    assert "events" in result
    assert isinstance(result["events"], list)


@pytest.mark.asyncio
async def test_calendar_create_event():
    """Test creating calendar event"""
    result = await calendar_server.execute_tool("create_event", {
        "title": "Test Meeting",
        "start_time": "2024-01-15T10:00:00",
        "end_time": "2024-01-15T11:00:00"
    })
    assert result["status"] == "success"
    assert "event" in result


@pytest.mark.asyncio
async def test_gmail_get_emails():
    """Test getting emails"""
    result = await gmail_server.execute_tool("get_emails", {"limit": 5})
    assert result["status"] == "success"
    assert "emails" in result
    assert isinstance(result["emails"], list)


@pytest.mark.asyncio
async def test_gmail_send_email():
    """Test sending email"""
    result = await gmail_server.execute_tool("send_email", {
        "to": "recipient@example.com",
        "subject": "Test Email",
        "body": "This is a test email"
    })
    assert result["status"] == "success"


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
