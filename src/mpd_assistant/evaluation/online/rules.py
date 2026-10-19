"""Deterministic response checks that run on every turn (no LLM). The LLM judge is sampled separately."""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from mpd_assistant.observability.metrics import PII_DETECTIONS
from mpd_assistant.privacy.detector import detect


class Verdict(str, Enum):
    PASS = "pass"
    REVISE = "revise"
    ESCALATE = "escalate"


@dataclass
class Evaluation:
    verdict: Verdict
    reasons: List[str] = field(default_factory=list)


_PLACEHOLDER_RE = re.compile(r"<[A-Z_]+_\d+>")
_REFUSAL_LEAK_RE = re.compile(r"(?i)\b(as an ai language model|i cannot access|system prompt|ignore previous instructions)\b")
_TOOL_SYNTAX_RE = re.compile(r"(?i)\bTOOL:\s*\w+|<tool_call>|\"tool\"\s*:")
_FRENCH_HINT = re.compile(r"(?i)\b(le|la|les|des|vous|nous|est|pour|avec|bonjour|merci)\b")
_ENGLISH_HINT = re.compile(r"(?i)\b(the|and|you|your|with|for|is|are|hello|thanks)\b")


def evaluate_response(
    response: Optional[str],
    *,
    language: str = "en",
    allowed_pii: tuple = (),
    allow_tokens: bool = False,
    max_chars: int = 4000,
) -> Evaluation:
    reasons: List[str] = []
    if not response or not response.strip():
        return Evaluation(Verdict.REVISE, ["empty_response"])

    leaked = [m for m in detect(response) if m.text not in allowed_pii]
    if leaked:
        for m in leaked:
            PII_DETECTIONS.labels("B7_reply", m.type).inc()
        return Evaluation(Verdict.ESCALATE, ["pii_leak"])  # never auto-revise a leak into a reply
    if not allow_tokens and _PLACEHOLDER_RE.search(response):
        reasons.append("unresolved_pii_token")
    if _TOOL_SYNTAX_RE.search(response):
        reasons.append("tool_syntax_leak")
    if _REFUSAL_LEAK_RE.search(response):
        reasons.append("prompt_or_boilerplate_leak")
    if len(response) > max_chars:
        reasons.append("too_long")

    fr, en = len(_FRENCH_HINT.findall(response)), len(_ENGLISH_HINT.findall(response))
    if language == "fr" and en >= 3 and en > fr * 2:
        reasons.append("wrong_language")
    if language == "en" and fr >= 3 and fr > en * 2:
        reasons.append("wrong_language")

    return Evaluation(Verdict.REVISE if reasons else Verdict.PASS, reasons)
