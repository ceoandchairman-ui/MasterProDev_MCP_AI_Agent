"""Headers for calls from the host to the MCP tool servers."""

from typing import Dict, Optional

from .config import settings


def service_headers(trace_id: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if trace_id:
        headers["X-Trace-Id"] = trace_id
    if session_id:
        headers["X-Session-Id"] = session_id
    if settings.MCP_SERVICE_KEY:
        headers["Authorization"] = f"Bearer {settings.MCP_SERVICE_KEY}"
    return headers
