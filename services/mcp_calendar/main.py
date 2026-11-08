"""Calendar MCP server. Every call acts on the calling user's own Google Calendar using their per-request access token.

Run:  uvicorn --factory services.mcp_calendar.main:create --port 8001
Nothing is stored here: no tokens, no events. Without a user token every tool answers `pending_auth`.
"""

import asyncio
import hashlib
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services._common.mcp_common.base_server import BaseMCPServer
from services._common.mcp_common.results import (
    clean_text,
    fail,
    int_in_range,
    missing,
    ok,
    pending_auth,
    valid_email,
    valid_id,
)
from services._common.mcp_common.user_token import current_user_token
from services.mcp_calendar.slots import MAX_WINDOW_DAYS, free_slots, parse_moment

DEFAULT_TIME_ZONE = os.environ.get("DEFAULT_TIME_ZONE", "America/Toronto")
MAX_EVENT_HOURS = 24
MAX_ATTENDEES = 10
_OFFSET_SUFFIX = re.compile(r"(Z|[+-]\d{2}:?\d{2})\Z")

ServiceFactory = Callable[[str], Any]  # access token -> Google Calendar service object


def resolve_time_zone(requested: Any) -> str:
    """A valid IANA zone name from the caller, else the configured default. Never trusts the raw string."""
    for candidate in (requested, DEFAULT_TIME_ZONE):
        if isinstance(candidate, str) and candidate:
            try:
                ZoneInfo(candidate)
                return candidate
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return "UTC"


def event_time(value: str, tz_name: str) -> Dict[str, str]:
    """A time that carries its own offset or Z is used as given; a local time gets the zone name."""
    if _OFFSET_SUFFIX.search(value):
        return {"dateTime": value}
    return {"dateTime": value, "timeZone": tz_name}


def event_id_for(idempotency_key: str) -> str:
    """Google accepts a caller-chosen event id of lowercase hex-like characters: the same key can never create two events."""
    return hashlib.sha256(idempotency_key.encode()).hexdigest()[:40]


def serialize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    start, end = event.get("start", {}), event.get("end", {})
    return {
        "id": event.get("id"),
        "title": event.get("summary"),
        "description": event.get("description", ""),
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "location": event.get("location"),
        "attendees": [a.get("email") for a in event.get("attendees", []) if a.get("email")],
        "htmlLink": event.get("htmlLink"),
    }


def _google_service(token: str) -> Any:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=Credentials(token=token), cache_discovery=False)


def _http_status(error: Exception) -> int | None:
    resp = getattr(error, "resp", None)
    status = getattr(resp, "status", None)
    return int(status) if status is not None else None


def google_failure(error: Exception) -> Dict[str, Any]:
    status = _http_status(error)
    if status is None:
        return fail("calendar_unavailable")
    if status == 401:
        return pending_auth("Google Calendar")
    if status == 403:
        return fail("calendar_forbidden")
    if status == 404:
        return fail("event_not_found")
    if status == 409:
        return fail("event_conflict")
    if status == 429:
        return fail("rate_limited")
    return fail("calendar_error")


def _zone(params: Dict[str, Any]) -> tuple[str, ZoneInfo]:
    name = resolve_time_zone(params.get("time_zone"))
    return name, ZoneInfo(name)


class CalendarMCPServer(BaseMCPServer):
    def __init__(self, service_factory: ServiceFactory = _google_service):
        super().__init__(name="Calendar Server", description="Per-user Google Calendar tools")
        self._factory = service_factory

    def get_available_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": "get_events", "description": "Upcoming events", "params": {"days": "int 1-30, default 7", "time_zone": "IANA name"}},
            {
                "name": "find_free_slots",
                "description": "Open slots inside working hours that do not clash with existing events",
                "params": {"start": "ISO 8601", "end": "ISO 8601", "duration_min": "int 15-480", "time_zone": "IANA name", "day_start": "HH:MM", "day_end": "HH:MM"},
            },
            {
                "name": "create_event",
                "description": "Create an event. Needs user confirmation.",
                "params": {"title": "str", "start_time": "ISO 8601", "end_time": "ISO 8601", "time_zone": "IANA name", "description": "str", "attendees": "list of emails", "idempotency_key": "str"},
            },
            {"name": "reschedule_event", "description": "Move an event. Needs user confirmation.", "params": {"event_id": "str", "start_time": "ISO 8601", "end_time": "ISO 8601", "time_zone": "IANA name"}},
            {"name": "delete_event", "description": "Delete an event. Needs user confirmation.", "params": {"event_id": "str"}},
        ]

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        handlers = {
            "get_events": self._get_events,
            "find_free_slots": self._find_free_slots,
            "create_event": self._create_event,
            "reschedule_event": self._reschedule_event,
            "delete_event": self._delete_event,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return fail("unknown_tool")
        token = current_user_token()
        if not token:
            return pending_auth("Google Calendar")
        try:
            service = await asyncio.to_thread(self._factory, token)
            return await handler(service, params if isinstance(params, dict) else {})
        except Exception as exc:  # any Google, network or parsing failure becomes a short code
            return google_failure(exc)

    async def _get_events(self, service: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        days = int_in_range(params.get("days"), 7, 1, 30)
        now = datetime.now(UTC)
        _, tz = _zone(params)

        def fetch() -> Dict[str, Any]:
            return service.events().list(
                calendarId="primary", timeMin=now.isoformat(), timeMax=(now + timedelta(days=days)).isoformat(),
                singleEvents=True, orderBy="startTime", timeZone=tz.key,
            ).execute()

        items = (await asyncio.to_thread(fetch)).get("items", [])
        events = [serialize_event(i) for i in items]
        return ok(events=events, count=len(events))

    async def _find_free_slots(self, service: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name, tz = _zone(params)
        try:
            start = parse_moment(str(params["start"]), tz) if params.get("start") else datetime.now(tz)
            end = parse_moment(str(params["end"]), tz) if params.get("end") else start + timedelta(days=7)
            day_start = datetime.strptime(str(params.get("day_start", "09:00")), "%H:%M").time()
            day_end = datetime.strptime(str(params.get("day_end", "17:00")), "%H:%M").time()
        except (ValueError, TypeError):
            return fail("invalid_time")
        if end <= start or end - start > timedelta(days=MAX_WINDOW_DAYS) or day_end <= day_start:
            return fail("invalid_window")
        duration = timedelta(minutes=int_in_range(params.get("duration_min"), 30, 15, 480))

        def query() -> Dict[str, Any]:
            body = {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "timeZone": name, "items": [{"id": "primary"}]}
            return service.freebusy().query(body=body).execute()

        raw = (await asyncio.to_thread(query)).get("calendars", {}).get("primary", {}).get("busy", [])
        busy = [(parse_moment(b["start"], tz), parse_moment(b["end"], tz)) for b in raw]
        slots = free_slots(busy, start, end, duration, tz, day_start, day_end)
        return ok(slots=slots, count=len(slots), time_zone=name)

    @staticmethod
    def _window(params: Dict[str, Any]) -> tuple[Dict[str, str] | None, Dict[str, str] | None, Dict[str, Any] | None]:
        name, tz = _zone(params)
        try:
            start, end = parse_moment(str(params["start_time"]), tz), parse_moment(str(params["end_time"]), tz)
        except (ValueError, TypeError, KeyError):
            return None, None, fail("invalid_time")
        if end <= start or end - start > timedelta(hours=MAX_EVENT_HOURS):
            return None, None, fail("invalid_window")
        return event_time(str(params["start_time"]), name), event_time(str(params["end_time"]), name), None

    async def _create_event(self, service: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        absent = missing(params, "title", "start_time", "end_time")
        if absent:
            return fail("missing_field", field=absent)
        start, end, problem = self._window(params)
        if problem:
            return problem
        attendees = params.get("attendees") or []
        if not isinstance(attendees, list) or len(attendees) > MAX_ATTENDEES or not all(valid_email(a) for a in attendees):
            return fail("invalid_attendees")
        body: Dict[str, Any] = {
            "summary": clean_text(params["title"], 200),
            "description": clean_text(params.get("description", ""), 4000),
            "start": start,
            "end": end,
        }
        if attendees:
            body["attendees"] = [{"email": valid_email(a)} for a in attendees]
        key = clean_text(params.get("idempotency_key"), 200)
        if key:
            body["id"] = event_id_for(key)

        def create() -> Dict[str, Any]:
            return service.events().insert(calendarId="primary", body=body, sendUpdates="all" if attendees else "none").execute()

        try:
            created = await asyncio.to_thread(create)
        except Exception as exc:
            if key and _http_status(exc) == 409:  # the same request already created this event
                existing = await asyncio.to_thread(lambda: service.events().get(calendarId="primary", eventId=body["id"]).execute())
                return ok(event=serialize_event(existing), duplicate=True)
            raise
        return ok(event=serialize_event(created))

    async def _reschedule_event(self, service: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        event_id = valid_id(params.get("event_id"))
        if event_id is None:
            return fail("invalid_event_id")
        start, end, problem = self._window(params)
        if problem:
            return problem

        def patch() -> Dict[str, Any]:
            return service.events().patch(calendarId="primary", eventId=event_id, body={"start": start, "end": end}, sendUpdates="all").execute()

        return ok(event=serialize_event(await asyncio.to_thread(patch)))

    async def _delete_event(self, service: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        event_id = valid_id(params.get("event_id"))
        if event_id is None:
            return fail("invalid_event_id")
        await asyncio.to_thread(lambda: service.events().delete(calendarId="primary", eventId=event_id).execute())
        return ok(event_id=event_id)


def create():
    """ASGI factory: uvicorn --factory services.mcp_calendar.main:create"""
    return CalendarMCPServer().app
