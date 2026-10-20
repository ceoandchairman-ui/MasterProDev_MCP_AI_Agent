"""Calendar and Gmail tool services, driven by fake Google clients (no network)."""

import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from services.mcp_calendar.main import CalendarMCPServer, event_id_for, event_time, resolve_time_zone
from services.mcp_calendar.slots import free_slots, merge_busy, parse_moment
from services.mcp_gmail.main import GmailMCPServer
from services.mcp_gmail.message import InvalidMessage, build_message, extract_body, html_to_text, parse_recipients

TORONTO = ZoneInfo("America/Toronto")
HEADERS = {"Authorization": "Bearer svc", "X-Google-Access-Token": "USER-TOKEN"}


class HttpErr(Exception):
    def __init__(self, status):
        self.resp = type("R", (), {"status": status})()


class Call:
    def __init__(self, result=None, error=None):
        self._result, self._error = result, error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class FakeCalendar:
    def __init__(self):
        self.inserted, self.patched, self.deleted, self.busy = [], [], [], []
        self.insert_error = None

    def events(self):
        return self

    def freebusy(self):
        return self

    def query(self, body):
        return Call({"calendars": {"primary": {"busy": self.busy}}})

    def list(self, **kw):
        return Call({"items": [{"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-11-02T09:00:00-05:00"}, "end": {"dateTime": "2026-11-02T09:30:00-05:00"}}]})

    def insert(self, calendarId, body, sendUpdates):
        self.inserted.append((body, sendUpdates))
        return Call({**body, "id": body.get("id", "new1")}, self.insert_error)

    def get(self, calendarId, eventId):
        return Call({"id": eventId, "summary": "existing", "start": {"dateTime": "x"}, "end": {"dateTime": "y"}})

    def patch(self, calendarId, eventId, body, sendUpdates):
        self.patched.append((eventId, body))
        return Call({"id": eventId, "summary": "moved", **body})

    def delete(self, calendarId, eventId):
        self.deleted.append(eventId)
        return Call({})


@pytest.fixture
def calendar(monkeypatch):
    monkeypatch.setenv("MCP_SERVICE_KEY", "svc")
    fake = FakeCalendar()
    server = CalendarMCPServer(service_factory=lambda token: fake)
    return TestClient(server.app), fake


def call(client, tool, params, headers=HEADERS):
    return client.post("/call", params={"tool_name": tool}, json=params, headers=headers).json()


# --- slots -------------------------------------------------------------------------------
def test_merge_busy_joins_overlaps():
    a, b, c = (datetime(2026, 11, 2, h, 0, tzinfo=TORONTO) for h in (9, 10, 11))
    assert merge_busy([(a, b), (a + timedelta(minutes=30), c)]) == [(a, c)]


def test_free_slots_skip_busy_time_and_weekends():
    start = datetime(2026, 11, 6, 9, 0, tzinfo=TORONTO)  # a Friday
    busy = [(datetime(2026, 11, 6, 9, 0, tzinfo=TORONTO), datetime(2026, 11, 6, 15, 0, tzinfo=TORONTO))]
    slots = free_slots(busy, start, start + timedelta(days=4), timedelta(minutes=30), TORONTO, max_slots=6)
    assert slots[0]["start"].startswith("2026-11-06T15:00")  # first gap after the meeting block
    assert all(not s["start"].startswith(("2026-11-07", "2026-11-08")) for s in slots)  # Saturday and Sunday skipped
    assert slots[-1]["start"].startswith("2026-11-09")


def test_free_slots_rejects_bad_window():
    start = datetime(2026, 11, 2, 9, 0, tzinfo=TORONTO)
    assert free_slots([], start, start - timedelta(hours=1), timedelta(minutes=30), TORONTO) == []
    assert free_slots([], start, start + timedelta(hours=1), timedelta(0), TORONTO) == []


def test_parse_moment_reads_naive_in_given_zone():
    assert parse_moment("2026-11-02T14:00:00", TORONTO).utcoffset() == timedelta(hours=-5)
    assert parse_moment("2026-11-02T14:00:00Z", TORONTO).hour == 9


# --- calendar server ---------------------------------------------------------------------
def test_zone_and_event_time_helpers():
    assert resolve_time_zone("Europe/Paris") == "Europe/Paris"
    assert resolve_time_zone("not/a/zone") == "America/Toronto"
    assert event_time("2026-11-02T14:00:00", "America/Toronto")["timeZone"] == "America/Toronto"
    assert event_time("2026-11-02T14:00:00Z", "America/Toronto") == {"dateTime": "2026-11-02T14:00:00Z"}
    assert event_id_for("k") == event_id_for("k") and event_id_for("k") != event_id_for("j")


def test_calendar_without_user_token_is_pending_auth(calendar):
    client, _ = calendar
    out = call(client, "get_events", {}, headers={"Authorization": "Bearer svc"})
    assert out["status"] == "pending_auth"


def test_calendar_requires_service_key(calendar):
    client, _ = calendar
    assert client.post("/call", params={"tool_name": "get_events"}, json={}).status_code == 401


def test_get_events_and_free_slots(calendar):
    client, fake = calendar
    assert call(client, "get_events", {"days": 3})["events"][0]["title"] == "Standup"
    fake.busy = [{"start": "2026-11-02T14:00:00Z", "end": "2026-11-02T15:00:00Z"}]  # 09:00-10:00 Toronto
    out = call(client, "find_free_slots", {"start": "2026-11-02T09:00:00", "end": "2026-11-02T12:00:00", "duration_min": 60, "time_zone": "America/Toronto"})
    assert out["status"] == "success" and out["slots"][0]["start"].startswith("2026-11-02T10:00")


def test_free_slots_rejects_inverted_window(calendar):
    client, _ = calendar
    out = call(client, "find_free_slots", {"start": "2026-11-03T09:00:00", "end": "2026-11-02T09:00:00"})
    assert out == {"status": "error", "error": "invalid_window"}


def test_create_event_validates_and_is_idempotent(calendar):
    client, fake = calendar
    assert call(client, "create_event", {"title": "x"})["error"] == "missing_field"
    bad = call(client, "create_event", {"title": "Call", "start_time": "2026-11-02T15:00:00", "end_time": "2026-11-02T14:00:00"})
    assert bad["error"] == "invalid_window"
    assert call(client, "create_event", {"title": "Call", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T14:30:00", "attendees": ["not-an-address"]})["error"] == "invalid_attendees"
    ok = call(client, "create_event", {"title": "Call", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T14:30:00", "attendees": ["ann@example.com"], "idempotency_key": "s1:abc"})
    assert ok["status"] == "success" and fake.inserted[0][0]["id"] == event_id_for("s1:abc") and fake.inserted[0][1] == "all"
    fake.insert_error = HttpErr(409)  # the same key again: Google reports a duplicate id
    again = call(client, "create_event", {"title": "Call", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T14:30:00", "idempotency_key": "s1:abc"})
    assert again["status"] == "success" and again["duplicate"] is True


def test_reschedule_and_delete_validate_ids(calendar):
    client, fake = calendar
    assert call(client, "reschedule_event", {"event_id": "[REQUIRES_ID]", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T15:00:00"})["error"] == "invalid_event_id"
    moved = call(client, "reschedule_event", {"event_id": "abcde12345", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T15:00:00"})
    assert moved["status"] == "success" and fake.patched[0][0] == "abcde12345"
    assert call(client, "delete_event", {"event_id": "no"})["error"] == "invalid_event_id"
    assert call(client, "delete_event", {"event_id": "abcde12345"})["status"] == "success" and fake.deleted == ["abcde12345"]


def test_google_errors_become_short_codes(calendar):
    client, fake = calendar
    fake.insert_error = HttpErr(403)
    out = call(client, "create_event", {"title": "Call", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T14:30:00"})
    assert out == {"status": "error", "error": "calendar_forbidden"}
    fake.insert_error = HttpErr(401)
    assert call(client, "create_event", {"title": "Call", "start_time": "2026-11-02T14:00:00", "end_time": "2026-11-02T14:30:00"})["status"] == "pending_auth"
    assert call(client, "nope", {})["error"] == "unknown_tool"


# --- gmail helpers -----------------------------------------------------------------------
def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_recipients_are_validated():
    assert parse_recipients("a@example.com, b@example.com") == ["a@example.com", "b@example.com"]
    with pytest.raises(InvalidMessage):
        parse_recipients("a@example.com, not-an-address")
    with pytest.raises(InvalidMessage):
        parse_recipients(["a@example.com"] * 11)


def test_build_message_blocks_header_injection():
    msg = build_message({"to": "a@example.com", "subject": "Hello\r\nBcc: evil@example.com", "body": "Hi"})
    assert "Bcc" not in msg and "\n" not in msg["Subject"]
    with pytest.raises(InvalidMessage):
        build_message({"to": "a@example.com\nBcc: evil@example.com", "subject": "s", "body": "b"})
    with pytest.raises(InvalidMessage):
        build_message({"to": "a@example.com", "subject": "", "body": "b"})
    with pytest.raises(InvalidMessage):
        build_message({"to": "a@example.com", "subject": "s", "body": "  "})


def test_extract_body_prefers_plain_and_handles_html_only():
    nested = {"mimeType": "multipart/mixed", "parts": [{"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/plain", "body": {"data": b64("plain text")}}, {"mimeType": "text/html", "body": {"data": b64("<p>html</p>")}}]}]}
    assert extract_body(nested) == "plain text"
    only_html = {"mimeType": "text/html", "body": {"data": b64("<style>x{}</style><p>Hello&nbsp;<b>there</b></p><script>bad()</script>")}}
    assert "Hello" in extract_body(only_html) and "bad()" not in extract_body(only_html) and "<" not in extract_body(only_html)
    assert html_to_text("a<br>b") == "a\nb"
    assert len(extract_body({"mimeType": "text/plain", "body": {"data": b64("x" * 20000)}}, limit=100)) == 100


# --- gmail server ------------------------------------------------------------------------
class FakeGmail:
    def __init__(self):
        self.sent, self.draft_log = [], []

    def users(self):
        return self

    def messages(self):
        return self

    def drafts(self):
        outer = self

        class Drafts:
            def create(self, userId, body):
                outer.draft_log.append(body)
                return Call({"id": "d1"})

        return Drafts()

    def list(self, **kw):
        return Call({"messages": [{"id": "m1"}]})

    def get(self, userId, id, format, metadataHeaders=None):
        payload = {"headers": [{"name": "From", "value": "ann@example.com"}, {"name": "Subject", "value": "Hi"}], "mimeType": "text/plain", "body": {"data": b64("body text")}}
        return Call({"id": id, "snippet": "snip", "payload": payload})

    def send(self, userId, body):
        self.sent.append(body)
        return Call({"id": "sent1"})


@pytest.fixture
def gmail(monkeypatch):
    monkeypatch.setenv("MCP_SERVICE_KEY", "svc")
    fake = FakeGmail()
    return TestClient(GmailMCPServer(service_factory=lambda token: fake).app), fake


def test_gmail_read_tools(gmail):
    client, _ = gmail
    listing = call(client, "get_emails", {"limit": 5})
    assert listing["emails"][0]["subject"] == "Hi" and listing["count"] == 1
    mail = call(client, "read_email", {"email_id": "m1abcde"})
    assert mail["email"]["body"] == "body text" and mail["untrusted"] is True
    assert call(client, "read_email", {"email_id": "../x"})["error"] == "invalid_email_id"
    assert call(client, "get_emails", {}, headers={"Authorization": "Bearer svc"})["status"] == "pending_auth"


def test_gmail_send_is_idempotent_and_draft_does_not_send(gmail):
    client, fake = gmail
    params = {"to": "a@example.com", "subject": "Hello", "body": "Hi there", "idempotency_key": "s1:k"}
    first, second = call(client, "send_email", params), call(client, "send_email", params)
    assert first["status"] == "success" and second["duplicate"] is True and len(fake.sent) == 1
    assert call(client, "send_email", {"to": "bad", "subject": "s", "body": "b"})["error"] == "invalid_recipients"
    draft = call(client, "create_draft", {"to": "a@example.com", "subject": "Hello", "body": "Hi"})
    assert draft["draft_id"] == "d1" and len(fake.sent) == 1
