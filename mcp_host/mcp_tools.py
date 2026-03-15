"""MCP Tool Wrappers for LangChain Integration"""

import logging
from typing import Optional, Type, Any, Dict
from pydantic import BaseModel, Field
from langchain.tools import BaseTool
import httpx
import uuid
import time
from functools import wraps

from .config import settings
from .rag_service import rag_service
from .resilience import api_retry_strategy, get_breaker
try:
    from mcp_host.main import TOOL_CALL_DURATION, TOOL_CALL_COUNTER
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Create circuit breakers for external services
calendar_breaker = get_breaker("calendar_server")
gmail_breaker = get_breaker("gmail_server")
rag_breaker = get_breaker("rag_service")


def instrumented_tool(func):
    """
    A decorator to instrument tool calls with Prometheus metrics.
    It records the duration and the success/error status of each call.
    """
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        tool_name = self.name
        start_time = time.time()
        status = "success"
        try:
            result = await func(self, *args, **kwargs)
            # Check the result dict for an internal error status
            if isinstance(result, dict) and result.get("status") == "error":
                status = "error"
            return result
        except Exception:
            status = "error"
            # Re-raise the exception to be handled by the agent
            raise
        finally:
            duration = time.time() - start_time
            if _PROMETHEUS_AVAILABLE:
                TOOL_CALL_DURATION.labels(tool_name=tool_name).observe(duration)
                TOOL_CALL_COUNTER.labels(tool_name=tool_name, status=status).inc()
    return wrapper


# ============================================================================
# CALENDAR TOOLS
# ============================================================================

class CalendarGetEventsInput(BaseModel):
    """Input schema for getting calendar events"""
    days: int = Field(
        default=7,
        description="Number of days ahead to fetch events (1-30)"
    )
    days_back: int = Field(
        default=365,
        description="Number of days in the past to fetch (for finding old/past appointments). Default 365 = 1 year back"
    )
    session_id: Optional[str] = Field(None, description="Internal session ID.")
    trace_id: Optional[str] = Field(None, description="Internal trace ID.")


class CalendarGetEventsTool(BaseTool):
    """Tool to get upcoming calendar events"""
    
    name: str = "get_calendar_events"
    description: str = """Get calendar events - both upcoming and past appointments.
    Use this when user asks about their schedule, meetings, or appointments.
    Can fetch future events (next N days) AND past events (last N days).
    Examples: 'What's on my calendar?', 'Show me my appointments from the last 3 months', 'Did I have a meeting last week?'"""
    args_schema: Type[BaseModel] = CalendarGetEventsInput
    
    def _run(self, days: int = 7, days_back: int = 365, session_id: Optional[str] = None, trace_id: Optional[str] = None) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    @instrumented_tool
    @api_retry_strategy
    async def _arun(self, days: int = 7, days_back: int = 365, session_id: Optional[str] = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Get calendar events asynchronously (both future and past)"""
        trace_id = trace_id or str(uuid.uuid4())
        headers = {"X-Trace-Id": trace_id, "X-Session-Id": session_id}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await calendar_breaker.execute_async(
                    client.post,
                    f"{settings.CALENDAR_SERVER_URL}/call",
                    params={"tool_name": "get_events"},
                    json={"days": days, "days_back": days_back},
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"[{trace_id}] ✓ Retrieved {result.get('count', 0)} calendar events")
                return result
        except Exception as e:
            logger.error(f"[{trace_id}] ✗ Calendar tool error: {e}")
            return {"status": "error", "error": str(e)}


class CalendarCreateEventInput(BaseModel):
    """Input schema for creating calendar events"""
    title: str = Field(description="Event title/summary")
    start_time: str = Field(description="Start time in ISO8601 format (e.g., 2025-12-15T14:00:00)")
    end_time: str = Field(description="End time in ISO8601 format (e.g., 2025-12-15T15:00:00)")
    description: Optional[str] = Field(default="", description="Optional event description")
    session_id: Optional[str] = Field(None, description="Internal session ID.")
    trace_id: Optional[str] = Field(None, description="Internal trace ID.")


class CalendarCreateEventTool(BaseTool):
    """Tool to create new calendar events"""
    
    name: str = "create_calendar_event"
    description: str = """Create a new calendar event/meeting.
    Use this when user wants to schedule, book, or create meetings/appointments.
    Examples: 'Schedule a meeting with John at 2pm', 'Book lunch tomorrow at noon'"""
    args_schema: Type[BaseModel] = CalendarCreateEventInput
    
    def _run(self, title: str, start_time: str, end_time: str, description: str = "", session_id: Optional[str] = None, trace_id: Optional[str] = None) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    @instrumented_tool
    @api_retry_strategy
    async def _arun(
        self, 
        title: str, 
        start_time: str, 
        end_time: str, 
        description: str = "",
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create calendar event asynchronously"""
        trace_id = trace_id or str(uuid.uuid4())
        headers = {"X-Trace-Id": trace_id, "X-Session-Id": session_id}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await calendar_breaker.execute_async(
                    client.post,
                    f"{settings.CALENDAR_SERVER_URL}/call",
                    params={"tool_name": "create_event"},
                    json={
                        "title": title,
                        "start_time": start_time,
                        "end_time": end_time,
                        "description": description
                    },
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"[{trace_id}] ✓ Created calendar event: {title}")
                return result
        except Exception as e:
            logger.error(f"[{trace_id}] ✗ Calendar create error: {e}")
            return {"status": "error", "error": str(e)}


class CalendarDeleteEventInput(BaseModel):
    """Input schema for deleting calendar events"""
    event_id: str = Field(description="ID of the event to delete")
    session_id: Optional[str] = Field(None, description="Internal session ID.")
    trace_id: Optional[str] = Field(None, description="Internal trace ID.")


class CalendarDeleteEventTool(BaseTool):
    """Tool to delete calendar events"""
    
    name: str = "delete_calendar_event"
    description: str = """Delete a calendar event by ID.
    CRITICAL: This tool requires an event_id parameter.
    WORKFLOW: First call get_calendar_events to find the event ID, then use this tool to delete it.
    This is a two-step process: (1) Fetch events with get_calendar_events, (2) Delete with event_id from results.
    Use when user wants to cancel/remove meetings: 'Cancel my 2pm meeting', 'Delete that appointment'.
    Example: User says 'delete that appointment' -> First get_calendar_events(days_back=90) -> Then delete_calendar_event(event_id='abc123')"""
    args_schema: Type[BaseModel] = CalendarDeleteEventInput
    
    def _run(self, event_id: str, session_id: Optional[str] = None, trace_id: Optional[str] = None) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    @instrumented_tool
    @api_retry_strategy
    async def _arun(self, event_id: str, session_id: Optional[str] = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Delete calendar event asynchronously"""
        trace_id = trace_id or str(uuid.uuid4())
        headers = {"X-Trace-Id": trace_id, "X-Session-Id": session_id}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await calendar_breaker.execute_async(
                    client.post,
                    f"{settings.CALENDAR_SERVER_URL}/call",
                    params={"tool_name": "delete_event"},
                    json={"event_id": event_id},
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"[{trace_id}] ✓ Deleted calendar event: {event_id}")
                return result
        except Exception as e:
            logger.error(f"[{trace_id}] ✗ Calendar delete error: {e}")
            return {"status": "error", "error": str(e)}


# ============================================================================
# KNOWLEDGE BASE TOOL
# ============================================================================

class KnowledgeSearchInput(BaseModel):
    """Input schema for searching the knowledge base"""
    query: str = Field(description="The question to ask the knowledge base.")
    trace_id: Optional[str] = Field(None, description="Internal trace ID.")


class KnowledgeSearchTool(BaseTool):
    """Tool to search the internal knowledge base for information."""
    
    name: str = "search_knowledge_base"
    description: str = """Search the internal knowledge base for documentation about tools, business policies, or other stored information.
    Use this when you are unsure how a tool works, what its parameters are, or what the rules are for performing an action.
    Example: 'What are the parameters for create_calendar_event?', 'What are the business hours for meetings?'"""
    args_schema: Type[BaseModel] = KnowledgeSearchInput
    
    def _run(self, query: str, trace_id: Optional[str] = None) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    @instrumented_tool
    @api_retry_strategy
    async def _arun(self, query: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Search the knowledge base asynchronously"""
        trace_id = trace_id or str(uuid.uuid4())
        try:
            # The RAG service is called locally, but we can still use a breaker
            # to protect against it becoming slow or unresponsive.
            logger.info(f"[{trace_id}] 🔍 Searching knowledge base for: '{query}'")
            
            results = await rag_breaker.execute_async(rag_service.search, query=query)
            
            logger.info(f"[{trace_id}] 📊 Knowledge base search returned {len(results)} result(s):")
            for i, result in enumerate(results, 1):
                logger.info(f"   [{trace_id}] Result {i}: {result.get('content', '')[:100]}...")
            
            return {"status": "success", "results": results}
        except Exception as e:
            logger.error(f"[{trace_id}] ✗ Knowledge base search error: {e}")
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
    session_id: Optional[str] = Field(None, description="Internal session ID.")
    trace_id: Optional[str] = Field(None, description="Internal trace ID.")


class GmailGetEmailsTool(BaseTool):
    """Tool to get recent emails"""
    
    name: str = "get_emails"
    description: str = """Get recent emails from Gmail inbox.
    Use this when user asks about emails, messages, or inbox.
    Supports search queries like 'is:unread', 'from:someone@email.com'.
    Examples: 'Check my emails', 'Any unread messages?', 'Emails from my boss'"""
    args_schema: Type[BaseModel] = GmailGetEmailsInput
    
    def _run(self, limit: int = 10, query: str = "", session_id: Optional[str] = None, trace_id: Optional[str] = None) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    @instrumented_tool
    @api_retry_strategy
    async def _arun(self, limit: int = 10, query: str = "", session_id: Optional[str] = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Get emails asynchronously"""
        trace_id = trace_id or str(uuid.uuid4())
        headers = {"X-Trace-Id": trace_id, "X-Session-Id": session_id}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await gmail_breaker.execute_async(
                    client.post,
                    f"{settings.GMAIL_SERVER_URL}/call",
                    params={"tool_name": "get_emails"},
                    json={"limit": limit, "query": query},
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"[{trace_id}] ✓ Retrieved {result.get('count', 0)} emails")
                return result
        except Exception as e:
            logger.error(f"[{trace_id}] ✗ Gmail get error: {e}")
            return {"status": "error", "error": str(e)}


class GmailSendEmailInput(BaseModel):
    """Input schema for sending emails"""
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body content")
    cc: Optional[str] = Field(default="", description="CC recipients (comma-separated)")
    bcc: Optional[str] = Field(default="", description="BCC recipients (comma-separated)")
    session_id: Optional[str] = Field(None, description="Internal session ID.")
    trace_id: Optional[str] = Field(None, description="Internal trace ID.")


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
        bcc: str = "",
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None
    ) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    @instrumented_tool
    @api_retry_strategy
    async def _arun(
        self, 
        to: str, 
        subject: str, 
        body: str, 
        cc: str = "", 
        bcc: str = "",
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send email asynchronously"""
        trace_id = trace_id or str(uuid.uuid4())
        headers = {"X-Trace-Id": trace_id, "X-Session-Id": session_id}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await gmail_breaker.execute_async(
                    client.post,
                    f"{settings.GMAIL_SERVER_URL}/call",
                    params={"tool_name": "send_email"},
                    json={
                        "to": to,
                        "subject": subject,
                        "body": body,
                        "cc": cc,
                        "bcc": bcc
                    },
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"[{trace_id}] ✓ Sent email to: {to}")
                return result
        except Exception as e:
            logger.error(f"[{trace_id}] ✗ Gmail send error: {e}")
            return {"status": "error", "error": str(e)}


class GmailReadEmailInput(BaseModel):
    """Input schema for reading full email content"""
    email_id: str = Field(description="ID of the email to read")
    session_id: Optional[str] = Field(None, description="Internal session ID.")
    trace_id: Optional[str] = Field(None, description="Internal trace ID.")


class GmailReadEmailTool(BaseTool):
    """Tool to read full email content"""
    
    name: str = "read_email"
    description: str = """Read the full content of a specific email by ID.
    Use this when you need to see the complete email body or attachments.
    First use get_emails to find the email ID, then use this to read it.
    Examples: 'Read that email from my boss', 'Show me the full email'"""
    args_schema: Type[BaseModel] = GmailReadEmailInput
    
    def _run(self, email_id: str, session_id: Optional[str] = None, trace_id: Optional[str] = None) -> str:
        """Synchronous run (not used in async context)"""
        raise NotImplementedError("Use async version")
    
    @instrumented_tool
    @api_retry_strategy
    async def _arun(self, email_id: str, session_id: Optional[str] = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Read email asynchronously"""
        trace_id = trace_id or str(uuid.uuid4())
        headers = {"X-Trace-Id": trace_id, "X-Session-Id": session_id}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await gmail_breaker.execute_async(
                    client.post,
                    f"{settings.GMAIL_SERVER_URL}/call",
                    params={"tool_name": "read_email"},
                    json={"email_id": email_id},
                    headers=headers
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"[{trace_id}] ✓ Read email: {email_id}")
                return result
        except Exception as e:
            logger.error(f"[{trace_id}] ✗ Gmail read error: {e}")
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
        
        # Knowledge base tools
        KnowledgeSearchTool(),
        
        # Gmail tools
        GmailGetEmailsTool(),
        GmailSendEmailTool(),
        GmailReadEmailTool(),
    ]


async def execute_tool_by_name(tool_name: str, params: Dict[str, Any], trace_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute a tool by name with the given parameters.
    
    This function looks up a tool from the registry and executes it asynchronously.
    Used for resuming pending actions after authentication interruptions.
    
    Args:
        tool_name: Name of the tool to execute (e.g., "create_calendar_event")
        params: Dictionary of parameters to pass to the tool
        trace_id: Optional trace ID for logging and propagation.
    
    Returns:
        Result dictionary from the tool execution
    """
    # Get all available tools
    tools = get_all_mcp_tools()
    
    # Find the tool with matching name
    matching_tool = None
    for tool in tools:
        if tool.name == tool_name:
            matching_tool = tool
            break
    
    if not matching_tool:
        logger.error(f"[{trace_id}] Tool '{tool_name}' not found.")
        return {
            "status": "error",
            "message": f"Tool '{tool_name}' not found. Available tools: {[t.name for t in tools]}"
        }
    
    try:
        # Add trace_id to params if the tool supports it
        if "trace_id" in matching_tool.args_schema.__fields__:
            params["trace_id"] = trace_id
            
        # Execute the tool asynchronously with the provided parameters
        logger.info(f"[{trace_id}] Executing resumed tool '{tool_name}'")
        result = await matching_tool.arun(**params)
        return result
    except Exception as e:
        logger.error(f"[{trace_id}] Error executing resumed tool {tool_name}: {e}")
        return {
            "status": "error",
            "message": f"Error executing {tool_name}: {str(e)}"
        }
