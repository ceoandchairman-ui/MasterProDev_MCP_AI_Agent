"""How a reply is presented in each interaction mode, and which avatar state goes with it. Pure functions, no model calls.

Modes: "text" (the written reply only), "voice" (a short plain-spoken version, 1-3 sentences, no formatting) and "hybrid"
(the written reply plus a one-sentence spoken summary). The avatar state is chosen by rules from the intent, not by asking
the model to write tags, so it is predictable and cannot leak into the text a person reads.
"""

import re

MODES = ("text", "voice", "hybrid")
AVATAR_STATES = ("idle", "listening", "thinking", "delighted", "helpful")

VOICE_MAX_SENTENCES = 3
VOICE_MAX_CHARS = 300
HYBRID_MAX_CHARS = 200

_FENCE = re.compile(r"```.*?```", re.S)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_EMPHASIS = re.compile(r"(\*\*|__|~~|\*)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.M)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

_HELPFUL_INTENTS = {"faq", "knowledge_question", "project_inquiry", "scope_request", "quote_request", "book_meeting", "email_request", "payment_request"}
_FRIENDLY_INTENTS = {"greeting", "small_talk"}
_HANDOVER_INTENTS = {"escalated", "human_request", "complaint"}


def plain_text(markdown: str) -> str:
    """The reply without Markdown, as one run of sentences that reads smoothly when spoken."""
    text = _FENCE.sub(" ", markdown)
    text = _IMAGE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("the link in the chat", text)
    text = text.replace("`", "")
    text = _EMPHASIS.sub("", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("", text)
    lines = []
    for line in (raw.strip() for raw in text.splitlines()):
        if line:
            lines.append(line if line[-1] in ".!?:;" else line + ".")
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _shorten(text: str, sentences: int, limit: int) -> str:
    kept = []
    for sentence in _SENTENCE_END.split(text):
        if kept and len(" ".join(kept + [sentence])) > limit:
            break
        kept.append(sentence)
        if len(kept) == sentences:
            break
    result = " ".join(kept)
    return result if len(result) <= limit else result[: limit - 1].rstrip() + "…"


def spoken_text(reply: str, mode: str) -> str | None:
    """What the client should read aloud: nothing for text mode, a short version for voice, a one-sentence summary for hybrid."""
    if mode not in ("voice", "hybrid"):
        return None
    plain = plain_text(reply)
    if not plain:
        return None
    if mode == "voice":
        return _shorten(plain, VOICE_MAX_SENTENCES, VOICE_MAX_CHARS)
    return _shorten(plain, 1, HYBRID_MAX_CHARS)


def avatar_state(intent: str, escalated: bool, reply: str) -> str:
    """idle, listening, delighted or helpful. 'thinking' is shown by the client while it waits, so it is never returned here."""
    if escalated or intent in _HANDOVER_INTENTS:
        return "helpful"
    if intent in _FRIENDLY_INTENTS:
        return "delighted"
    if reply.rstrip().endswith("?"):
        return "listening"
    if intent in _HELPFUL_INTENTS:
        return "helpful"
    return "idle"
