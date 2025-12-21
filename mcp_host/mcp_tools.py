"""MCP Tool Wrappers for LangChain Integration"""

import logging
from typing import Optional, Type, Any, Dict
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
import httpx

from .config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# CALENDAR TOOLS
# ============================================================================

class CalendarGetEventsInput(BaseModel):
    """Input schema for getting calendar events"""
    days: int = Field(
        default=7,
        description="Number of days ahead to fetch events (1-30)"
    )


class CalendarGetEventsTool(BaseTool):
    """Tool to get upcoming calendar events"""
    
    name: str = "get_calendar_events"
    description: str = """Get upcoming calendar events for the next N days.
    Use this when user asks about their schedule, meetings, or appointments.
    Examples: 'What's on my calendar?', 'Do I have meetings tomorrow?'"""
    args_schema: Type[BaseModel] = CalendarGetEventsInput
    
    def _run(self, days: int = 7) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    async def _arun(self, days: int = 7) -> Dict[str, Any]:
        """Get calendar events asynchronously"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.CALENDAR_SERVER_URL}/call",
                    params={"tool_name": "get_events"},
                    json={"days": days}
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"✓ Retrieved {result.get('count', 0)} calendar events")
                return result
        except Exception as e:
            logger.error(f"✗ Calendar tool error: {e}")
            return {"status": "error", "error": str(e)}


class CalendarCreateEventInput(BaseModel):
    """Input schema for creating calendar events"""
    title: str = Field(description="Event title/summary")
    start_time: str = Field(description="Start time in ISO8601 format (e.g., 2025-12-15T14:00:00)")
    end_time: str = Field(description="End time in ISO8601 format (e.g., 2025-12-15T15:00:00)")
    description: Optional[str] = Field(default="", description="Optional event description")


class CalendarCreateEventTool(BaseTool):
    """Tool to create new calendar events"""
    
    name: str = "create_calendar_event"
    description: str = """Create a new calendar event/meeting.
    Use this when user wants to schedule, book, or create meetings/appointments.
    Examples: 'Schedule a meeting with John at 2pm', 'Book lunch tomorrow at noon'"""
    args_schema: Type[BaseModel] = CalendarCreateEventInput
    
    def _run(self, title: str, start_time: str, end_time: str, description: str = "") -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    async def _arun(
        self, 
        title: str, 
        start_time: str, 
        end_time: str, 
        description: str = ""
    ) -> Dict[str, Any]:
        """Create calendar event asynchronously"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.CALENDAR_SERVER_URL}/call",
                    params={"tool_name": "create_event"},
                    json={
                        "title": title,
                        "start_time": start_time,
                        "end_time": end_time,
                        "description": description
                    }
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"✓ Created calendar event: {title}")
                return result
        except Exception as e:
            logger.error(f"✗ Calendar create error: {e}")
            return {"status": "error", "error": str(e)}


class CalendarDeleteEventInput(BaseModel):
    """Input schema for deleting calendar events"""
    event_id: str = Field(description="ID of the event to delete")


class CalendarDeleteEventTool(BaseTool):
    """Tool to delete calendar events"""
    
    name: str = "delete_calendar_event"
    description: str = """Delete a calendar event by ID.
    Use this when user wants to cancel or remove a meeting/appointment.
    Examples: 'Cancel my 2pm meeting', 'Delete tomorrow's appointment'"""
    args_schema: Type[BaseModel] = CalendarDeleteEventInput
    
    def _run(self, event_id: str) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    async def _arun(self, event_id: str) -> Dict[str, Any]:
        """Delete calendar event asynchronously"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.CALENDAR_SERVER_URL}/call",
                    params={"tool_name": "delete_event"},
                    json={"event_id": event_id}
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"✓ Deleted calendar event: {event_id}")
                return result
        except Exception as e:
            logger.error(f"✗ Calendar delete error: {e}")
            return {"status": "error", "error": str(e)}


# ============================================================================
# GMAIL TOOLS
# ============================================================================

class GmailGetEmailsInput(BaseModel):
    """Input schema for getting emails"""
    limit: int = Field(
        default=10,
        description="Maximum number of emails to fetch (1-50)"
    )
    query: Optional[str] = Field(
        default="",
        description="Search query (e.g., 'is:unread', 'from:boss@company.com')"
    )


class GmailGetEmailsTool(BaseTool):
    """Tool to get recent emails"""
    
    name: str = "get_emails"
    description: str = """Get recent emails from Gmail inbox.
    Use this when user asks about emails, messages, or inbox.
    Supports search queries like 'is:unread', 'from:someone@email.com'.
    Examples: 'Check my emails', 'Any unread messages?', 'Emails from my boss'"""
    args_schema: Type[BaseModel] = GmailGetEmailsInput
    
    def _run(self, limit: int = 10, query: str = "") -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    async def _arun(self, limit: int = 10, query: str = "") -> Dict[str, Any]:
        """Get emails asynchronously"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.GMAIL_SERVER_URL}/call",
                    params={"tool_name": "get_emails"},
                    json={"limit": limit, "query": query}
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"✓ Retrieved {result.get('count', 0)} emails")
                return result
        except Exception as e:
            logger.error(f"✗ Gmail get error: {e}")
            return {"status": "error", "error": str(e)}


class GmailSendEmailInput(BaseModel):
    """Input schema for sending emails"""
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body content")
    cc: Optional[str] = Field(default="", description="CC recipients (comma-separated)")
    bcc: Optional[str] = Field(default="", description="BCC recipients (comma-separated)")


class GmailSendEmailTool(BaseTool):
    """Tool to send emails"""
    
    name: str = "send_email"
    description: str = """Send an email via Gmail.
    Use this when user wants to send, compose, or email someone.
    Examples: 'Send email to john@company.com', 'Email my boss about the report'"""
    args_schema: Type[BaseModel] = GmailSendEmailInput
    
    def _run(
        self, 
        to: str, 
        subject: str, 
        body: str, 
        cc: str = "", 
        bcc: str = ""
    ) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    async def _arun(
        self, 
        to: str, 
        subject: str, 
        body: str, 
        cc: str = "", 
        bcc: str = ""
    ) -> Dict[str, Any]:
        """Send email asynchronously"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.GMAIL_SERVER_URL}/call",
                    params={"tool_name": "send_email"},
                    json={
                        "to": to,
                        "subject": subject,
                        "body": body,
                        "cc": cc,
                        "bcc": bcc
                    }
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"✓ Sent email to: {to}")
                return result
        except Exception as e:
            logger.error(f"✗ Gmail send error: {e}")
            return {"status": "error", "error": str(e)}


class GmailReadEmailInput(BaseModel):
    """Input schema for reading full email content"""
    email_id: str = Field(description="ID of the email to read")


class GmailReadEmailTool(BaseTool):
    """Tool to read full email content"""
    
    name: str = "read_email"
    description: str = """Read the full content of a specific email by ID.
    Use this when you need to see the complete email body or attachments.
    First use get_emails to find the email ID, then use this to read it.
    Examples: 'Read that email from my boss', 'Show me the full email'"""
    args_schema: Type[BaseModel] = GmailReadEmailInput
    
    def _run(self, email_id: str) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    async def _arun(self, email_id: str) -> Dict[str, Any]:
        """Read email asynchronously"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{settings.GMAIL_SERVER_URL}/call",
                    params={"tool_name": "read_email"},
                    json={"email_id": email_id}
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"✓ Read email: {email_id}")
                return result
        except Exception as e:
            logger.error(f"✗ Gmail read error: {e}")
            return {"status": "error", "error": str(e)}


# ============================================================================
# TOOL REGISTRY
# ============================================================================

def get_all_mcp_tools() -> list[BaseTool]:
    """Get all available MCP tools for the agent"""
    return [
        # Calendar tools
        CalendarGetEventsTool(),
        CalendarCreateEventTool(),
        CalendarDeleteEventTool(),
        
        # Gmail tools
        GmailGetEmailsTool(),
        GmailSendEmailTool(),
        GmailReadEmailTool(),
    ]
