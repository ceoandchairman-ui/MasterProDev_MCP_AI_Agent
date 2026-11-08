"""Interaction modes (text, voice, hybrid) and avatar states: the rules, and how the API returns them."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mpd_assistant.api.main import Services, create_app
from mpd_assistant.responses.presentation import AVATAR_STATES, avatar_state, plain_text, spoken_text
from mpd_assistant.sessions.service import MemorySessionRepository, SessionService

MARKDOWN = (
    "## Our **AI Agents** pillar\n\n"
    "We design and deploy agents that automate real workflows. They have *clear scope* and controls.\n\n"
    "- Support automation\n- Lead qualification\n\n"
    "See [the overview](https://example.com/agents) or https://example.com/more for details. Ask me anything else!"
)


def test_plain_text_removes_formatting_and_keeps_the_words():
    plain = plain_text(MARKDOWN)
    for leftover in ("**", "##", "](", "http", "- ", "*clear"):
        assert leftover not in plain
    assert "AI Agents pillar." in plain and "Support automation." in plain and "the overview" in plain and "the link in the chat" in plain


def test_text_mode_has_nothing_to_speak_voice_is_short_hybrid_is_one_sentence():
    assert spoken_text(MARKDOWN, "text") is None and spoken_text(MARKDOWN, "unknown") is None
    voice, hybrid = spoken_text(MARKDOWN, "voice"), spoken_text(MARKDOWN, "hybrid")
    assert voice.count(". ") <= 2 and len(voice) <= 300 and "**" not in voice
    assert hybrid == "Our AI Agents pillar." and len(hybrid) <= 200


def test_an_overlong_single_sentence_is_cut_with_an_ellipsis():
    cut = spoken_text("word " * 200, "hybrid")
    assert len(cut) <= 200 and cut.endswith("…")


@pytest.mark.parametrize("intent, escalated, reply, expected", [
    ("greeting", False, "Hello! How can I help?", "delighted"),
    ("small_talk", False, "Glad to hear it.", "delighted"),
    ("knowledge_question", False, "We build AI agents.", "helpful"),
    ("faq", False, "Which pillar interests you?", "listening"),
    ("quote_request", True, "Connecting you with our team.", "helpful"),
    ("human_request", False, "Of course.", "helpful"),
    ("unknown", False, "Okay.", "idle"),
])
def test_avatar_state_follows_the_intent_and_never_returns_thinking(intent, escalated, reply, expected):
    state = avatar_state(intent, escalated, reply)
    assert state == expected and state in AVATAR_STATES and state != "thinking"


class FakeChat:
    async def chat(self, thread_id, text, **kwargs):
        return SimpleNamespace(
            reply="Hello! I'm the **MasterProDev** assistant. How can I help you today?", escalated=False, reference=None,
            safe_user_text="", intent="greeting", agent="concierge", mode="templated",
        )


def client():
    return TestClient(create_app(Services(FakeChat(), SessionService(MemorySessionRepository()), identity=None)))


def test_plain_requests_are_unchanged():
    body = client().post("/v2/chat", json={"message": "hi"}).json()
    assert body["spoken"] is None and body["avatar_state"] is None and "**MasterProDev**" in body["reply"]


def test_voice_and_hybrid_add_a_spoken_version_and_the_avatar_adds_its_state():
    c = client()
    voice = c.post("/v2/chat", json={"message": "hi", "mode": "voice", "avatar": True}).json()
    assert voice["spoken"] == "Hello! I'm the MasterProDev assistant. How can I help you today?" and voice["avatar_state"] == "delighted"
    hybrid = c.post("/v2/chat", json={"message": "hi", "mode": "hybrid"}).json()
    assert hybrid["spoken"] == "Hello!" and hybrid["avatar_state"] is None
    assert c.post("/v2/chat", json={"message": "hi", "mode": "shouting"}).status_code == 422


def test_the_stream_carries_the_spoken_text_and_state_in_its_final_event():
    with client().stream("POST", "/v2/chat/stream", json={"message": "hi", "mode": "hybrid", "avatar": True}) as response:
        events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    done = events[-1]
    assert done["type"] == "done" and done["spoken"] == "Hello!" and done["avatar_state"] == "delighted"
    assert [e["type"] for e in events][:2] == ["thinking", "chunk"]
