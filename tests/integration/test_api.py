"""Integration tests for API endpoints"""

import io
import json
import textwrap

import pytest
from fastapi.testclient import TestClient
from mcp_host.main import app

client = TestClient(app)


# ── helpers ────────────────────────────────────────────────────────────────

def _txt_bytes():
    return textwrap.dedent("""\
        Quarterly Revenue Report – Q1 2026
        Total revenue: $4,200,000
        Units sold: 18,500
    """).encode()


def _csv_bytes():
    return b"name,score\nAlice,95\nBob,82\nCarla,78\n"


def _json_bytes():
    return json.dumps({"features": ["chat", "voice", "calendar"]}).encode()


def _minimal_pdf_bytes():
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R"
        b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"5 0 obj<</Length 44>>\nstream\n"
        b"BT /F1 12 Tf 50 750 Td (smoke test PDF) Tj ET\nendstream\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )


# ── existing tests ──────────────────────────────────────────────────────────

def test_health_check():
    """Test health endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "services" in data


def test_login():
    """Test login endpoint"""
    response = client.post("/login", json={
        "email": "test@example.com",
        "password": "test_password_123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_chat_without_auth():
    """Test chat endpoint without authentication"""
    response = client.post("/chat", json={
        "message": "Hello"
    })
    assert response.status_code == 401


def test_profile_without_auth():
    """Test profile endpoint without authentication"""
    response = client.get("/user/profile")
    assert response.status_code == 401


def test_conversations_without_auth():
    """Test conversations endpoint without authentication"""
    response = client.get("/conversations")
    assert response.status_code == 401


# ── file upload tests ───────────────────────────────────────────────────────

def test_chat_plain_message():
    """POST /chat with text only (no file) returns a response."""
    response = client.post("/chat", data={"message": "Say the word HELLO"})
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert "conversation_id" in data


def test_chat_txt_file_upload():
    """Upload a plain-text file and ask a question about its content."""
    response = client.post(
        "/chat",
        data={"message": "What is the total revenue mentioned?"},
        files={"file": ("report.txt", _txt_bytes(), "text/plain")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    lower = data["response"].lower()
    assert any(kw in lower for kw in ["4", "revenue", "report"]), \
        f"Revenue not reflected in response: {data['response'][:300]}"


def test_chat_csv_file_upload():
    """Upload a CSV and ask about its top scorer."""
    response = client.post(
        "/chat",
        data={"message": "Who has the highest score?"},
        files={"file": ("grades.csv", _csv_bytes(), "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    lower = data["response"].lower()
    assert "alice" in lower or "95" in lower, \
        f"Top scorer not in response: {data['response'][:300]}"


def test_chat_json_file_upload():
    """Upload a JSON file and ask about its content."""
    response = client.post(
        "/chat",
        data={"message": "List the features from this JSON."},
        files={"file": ("config.json", _json_bytes(), "application/json")},
    )
    assert response.status_code == 200
    data = response.json()
    lower = data["response"].lower()
    assert any(kw in lower for kw in ["chat", "voice", "calendar", "feature"]), \
        f"JSON features not reflected: {data['response'][:300]}"


def test_chat_pdf_file_upload():
    """Upload a minimal PDF — server should extract text without crashing."""
    response = client.post(
        "/chat",
        data={"message": "What does this PDF say?"},
        files={"file": ("test.pdf", _minimal_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "response" in data


def test_chat_unsupported_file_type():
    """Uploading an unsupported file type must not crash — backend returns a note."""
    response = client.post(
        "/chat",
        data={"message": "Here is an exe"},
        files={"file": ("bad.exe", b"\x4d\x5a" + b"\x00" * 64, "application/octet-stream")},
    )
    assert response.status_code == 200
    lower = response.json()["response"].lower()
    assert any(kw in lower for kw in ["not processed", "unsupported", "exe", "file"]), \
        f"Unsupported type not handled gracefully: {response.json()['response'][:300]}"


def test_chat_file_too_large():
    """A file exceeding 25 MB must be rejected gracefully."""
    big = b"x" * (26 * 1024 * 1024)  # 26 MB
    response = client.post(
        "/chat",
        data={"message": "Analyze this"},
        files={"file": ("huge.txt", big, "text/plain")},
    )
    assert response.status_code == 200
    lower = response.json()["response"].lower()
    assert any(kw in lower for kw in ["too large", "25", "mb", "size", "not processed"]), \
        f"Oversized file not flagged: {response.json()['response'][:300]}"


def test_chat_file_context_memory():
    """
    Turn 1 — upload file.
    Turn 2 — follow-up WITHOUT re-uploading.
    Agent must still reference the file content via stored file context.
    """
    r1 = client.post(
        "/chat",
        data={"message": "Remember the revenue in this file."},
        files={"file": ("q1.txt", _txt_bytes(), "text/plain")},
    )
    assert r1.status_code == 200
    conv_id = r1.json()["conversation_id"]

    r2 = client.post(
        "/chat",
        data={"message": "What was the revenue you saw?", "conversation_id": conv_id},
    )
    assert r2.status_code == 200
    lower2 = r2.json()["response"].lower()
    assert any(kw in lower2 for kw in ["4", "revenue", "million", "report"]), \
        f"File context not retained in follow-up: {r2.json()['response'][:300]}"


# ── streaming endpoint tests ────────────────────────────────────────────────

def test_chat_stream_basic():
    """POST /chat/stream returns SSE with chunk + done events."""
    with client.stream(
        "POST", "/chat/stream", data={"message": "Say the word STREAM_OK"}
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = []
        buffer = ""
        for text in resp.iter_text():
            buffer += text
            lines = buffer.split("\n")
            buffer = lines.pop()
            for line in lines:
                if line.startswith("data: "):
                    try:
                        events.append(json.loads(line[6:]))
                    except json.JSONDecodeError:
                        pass

    types = {e.get("type") for e in events}
    assert "chunk" in types, f"No chunk events in stream. Got: {events}"
    assert "done" in types,  f"No done  event in stream. Got: {events}"

    full_text = "".join(e.get("text", "") for e in events if e.get("type") == "chunk")
    assert len(full_text) > 0, "Streamed text was empty"


def test_chat_stream_with_file():
    """Streaming endpoint also processes an uploaded file correctly."""
    with client.stream(
        "POST", "/chat/stream",
        data={"message": "What total revenue is mentioned?"},
        files={"file": ("q1.txt", _txt_bytes(), "text/plain")},
    ) as resp:
        assert resp.status_code == 200
        full_text = ""
        buffer = ""
        for text in resp.iter_text():
            buffer += text
            lines = buffer.split("\n")
            buffer = lines.pop()
            for line in lines:
                if line.startswith("data: "):
                    try:
                        ev = json.loads(line[6:])
                        if ev.get("type") == "chunk":
                            full_text += ev.get("text", "")
                    except json.JSONDecodeError:
                        pass

    assert len(full_text) > 0
    assert any(kw in full_text.lower() for kw in ["4", "revenue", "report"]), \
        f"Revenue not in stream response: {full_text[:300]}"

