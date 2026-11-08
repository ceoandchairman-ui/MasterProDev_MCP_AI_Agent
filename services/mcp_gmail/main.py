"""Gmail MCP server. Every call acts on the calling user's own mailbox using their per-request access token.

Run:  uvicorn --factory services.mcp_gmail.main:create --port 8002
Nothing is stored here. Mail bodies are untrusted text: the application marks them so they cannot trigger side effects.
"""

import asyncio
import hashlib
import time
from collections.abc import Callable
from typing import Any, Dict, List

from services._common.mcp_common.base_server import BaseMCPServer
from services._common.mcp_common.results import fail, int_in_range, ok, pending_auth, valid_id
from services._common.mcp_common.user_token import current_user_token
from services.mcp_gmail.message import InvalidMessage, build_message, encode_raw, extract_body, headers_of

ServiceFactory = Callable[[str], Any]  # access token -> Google Gmail service object

DEDUPE_TTL_SECONDS = 600
DEDUPE_MAX_ENTRIES = 2000


def _google_service(token: str) -> Any:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=Credentials(token=token), cache_discovery=False)


def _http_status(error: Exception) -> int | None:
    status = getattr(getattr(error, "resp", None), "status", None)
    return int(status) if status is not None else None


def google_failure(error: Exception) -> Dict[str, Any]:
    status = _http_status(error)
    if status is None:
        return fail("mail_unavailable")
    if status == 401:
        return pending_auth("Gmail")
    if status == 403:
        return fail("mail_forbidden")
    if status == 404:
        return fail("email_not_found")
    if status == 429:
        return fail("rate_limited")
    return fail("mail_error")


class RecentSends:
    """Remembers sends by idempotency key for a few minutes, so a retried request cannot send the same mail twice."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._seen: Dict[str, tuple[float, Dict[str, Any]]] = {}
        self._clock = clock

    def get(self, key: str) -> Dict[str, Any] | None:
        entry = self._seen.get(key)
        if entry is None:
            return None
        if self._clock() - entry[0] > DEDUPE_TTL_SECONDS:
            del self._seen[key]
            return None
        return entry[1]

    def put(self, key: str, result: Dict[str, Any]) -> None:
        if len(self._seen) >= DEDUPE_MAX_ENTRIES:
            oldest = min(self._seen, key=lambda k: self._seen[k][0])
            del self._seen[oldest]
        self._seen[key] = (self._clock(), result)


class GmailMCPServer(BaseMCPServer):
    def __init__(self, service_factory: ServiceFactory = _google_service):
        super().__init__(name="Gmail Server", description="Per-user Gmail tools")
        self._factory = service_factory
        self._sent = RecentSends()

    def get_available_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "get_emails", "description": "Recent emails, optionally filtered by a search query", "params": {"limit": "int 1-25", "query": "Gmail search text"}},
            {"name": "read_email", "description": "Full text of one email", "params": {"email_id": "str"}},
            {"name": "create_draft", "description": "Save a draft without sending it", "params": {"to": "address", "subject": "str", "body": "str", "cc": "addresses"}},
            {
                "name": "send_email",
                "description": "Send an email. Needs user confirmation.",
                "params": {"to": "addresses", "subject": "str", "body": "str", "cc": "addresses", "bcc": "addresses", "idempotency_key": "str"},
            },
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        handlers = {
            "get_emails": self._get_emails,
            "read_email": self._read_email,
            "create_draft": self._create_draft,
            "send_email": self._send_email,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return fail("unknown_tool")
        token = current_user_token()
        if not token:
            return pending_auth("Gmail")
        try:
            service = await asyncio.to_thread(self._factory, token)
            return await handler(service, params if isinstance(params, dict) else {}, token)
        except InvalidMessage as exc:
            return fail(exc.code)
        except Exception as exc:  # any Google or network failure becomes a short code
            return google_failure(exc)

    async def _get_emails(self, service: Any, params: Dict[str, Any], token: str) -> Dict[str, Any]:
        limit = int_in_range(params.get("limit"), 10, 1, 25)
        query = str(params.get("query", ""))[:200]

        def fetch() -> List[Dict[str, Any]]:
            listing = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
            details = []
            for ref in listing.get("messages", [])[:limit]:
                details.append(
                    service.users().messages().get(userId="me", id=ref["id"], format="metadata", metadataHeaders=["From", "Subject", "Date"]).execute()
                )
            return details

        emails = []
        for detail in await asyncio.to_thread(fetch):
            headers = headers_of(detail.get("payload", {}))
            emails.append(
                {
                    "id": detail.get("id"),
                    "from": headers.get("From", "Unknown"),
                    "subject": headers.get("Subject", "(No Subject)"),
                    "date": headers.get("Date", ""),
                    "snippet": (detail.get("snippet") or "")[:200],
                }
            )
        return ok(emails=emails, count=len(emails))

    async def _read_email(self, service: Any, params: Dict[str, Any], token: str) -> Dict[str, Any]:
        email_id = valid_id(params.get("email_id"))
        if email_id is None:
            return fail("invalid_email_id")
        message = await asyncio.to_thread(lambda: service.users().messages().get(userId="me", id=email_id, format="full").execute())
        payload = message.get("payload", {})
        headers = headers_of(payload)
        return ok(
            email={
                "id": email_id,
                "from": headers.get("From", "Unknown"),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", "(No Subject)"),
                "date": headers.get("Date", ""),
                "body": extract_body(payload),
            },
            untrusted=True,
        )

    async def _create_draft(self, service: Any, params: Dict[str, Any], token: str) -> Dict[str, Any]:
        raw = encode_raw(build_message(params))
        draft = await asyncio.to_thread(lambda: service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute())
        return ok(draft_id=draft.get("id"))

    async def _send_email(self, service: Any, params: Dict[str, Any], token: str) -> Dict[str, Any]:
        message = build_message(params)
        key = params.get("idempotency_key")
        dedupe_key = None
        if isinstance(key, str) and key:
            dedupe_key = hashlib.sha256((token + "|" + key).encode()).hexdigest()
            prior = self._sent.get(dedupe_key)
            if prior is not None:
                return {**prior, "duplicate": True}
        raw = encode_raw(message)
        sent = await asyncio.to_thread(lambda: service.users().messages().send(userId="me", body={"raw": raw}).execute())
        result = ok(message_id=sent.get("id"))
        if dedupe_key is not None:
            self._sent.put(dedupe_key, result)
        return result


def create():
    """ASGI factory: uvicorn --factory services.mcp_gmail.main:create"""
    return GmailMCPServer().app
