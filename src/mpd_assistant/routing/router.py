"""Stage-1 router: deterministic rules. Stage 2 (small LLM) handles low-confidence cases later."""

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

from mpd_assistant.routing.intents import (
    GATED_INTENTS,
    INTENT_AGENT,
    INTENT_DEFAULT_MODE,
    Agent,
    Intent,
    Mode,
)

CONFIDENCE_THRESHOLD = 0.6


@dataclass(frozen=True)
class RouteDecision:
    intent: Intent
    agent: Agent
    mode: Mode
    confidence: float
    language: str
    requires_identity: bool


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower().strip()
    return re.sub(r"\s+", " ", text)


def detect_language(text: str) -> str:
    """Tiny heuristic (en/fr); replaced by a proper detector in the multilingual wave."""
    t = normalize(text)
    french = len(re.findall(r"\b(bonjour|salut|merci|je|vous|nous|s'il|veux|voudrais|rendez-vous|devis|prix|est-ce|quel|quelle)\b", t))
    english = len(re.findall(r"\b(hello|hi|thanks|thank|please|the|you|we|want|would|need|quote|price|what|how|can)\b", t))
    return "fr" if french > english else "en"


# (intent, patterns, confidence). Patterns use word boundaries so "hi" never matches "hire" or "history".
_RULES: List[Tuple[Intent, List[str], float]] = [
    (Intent.HUMAN_REQUEST, [r"\b(human|real person|agent|representative|speak to someone|talk to someone|parler (a|à) quelqu'un)\b"], 0.95),
    (Intent.COMPLAINT, [r"\b(complain|complaint|unacceptable|terrible|refund|furious|angry|scam)\b"], 0.85),
    (Intent.QUOTE_REQUEST, [r"\b(quote|quotation|pricing|price|cost|estimate|how much|devis|prix|tarif)\b"], 0.85),
    (Intent.BOOK_MEETING, [r"\b(prendre|fixer|planifier)\b.*\b(rendez-vous|rdv|appel|réunion)\b", r"\b(rendez-vous|rdv)\b", r"\b(book|schedule|set up|arrange)\b.*\b(meeting|call|demo|consultation|appointment)\b", r"\b(meeting|call|appointment|rendez-vous)\b.*\b(book|schedule|available|free)\b", r"\bavailability\b"], 0.85),
    (Intent.EMAIL_REQUEST, [r"\b(send|write|draft|reply)\b.*\b(email|e-mail|mail)\b", r"\b(my|check)\b.*\b(emails|inbox)\b"], 0.85),
    (Intent.SCOPE_REQUEST, [r"\b(scope|roadmap|requirements|architecture|proposal|technical plan|cahier des charges)\b"], 0.8),
    (Intent.PROJECT_INQUIRY, [r"\b(i|we) (want|need|would like|are looking) (to )?(build|develop|create|hire|start|get)\b", r"\b(build|develop|create)\b.*\b(app|website|platform|software|system|mvp|product)\b", r"\bhire (you|your team)\b"], 0.8),
    (Intent.GREETING, [r"^(hi|hello|hey|good (morning|afternoon|evening)|bonjour|salut)\b( (there|again|team|all))?[ !.,]*$"], 0.95),
    (Intent.SMALL_TALK, [r"^(thanks|thank you|merci|ok|okay|great|cool|bye|goodbye)\b[ !.,]*$", r"\b(how are you|who are you|what is your name)\b"], 0.8),
    (Intent.FAQ, [r"\b(what do you do|what services|services do you offer|where are you|location|opening hours|contact|about (you|masterprodev)|who is masterprodev)\b"], 0.8),
    (Intent.KNOWLEDGE_QUESTION, [r"\b(do you|can you|does masterprodev|have you)\b.*\?", r"^(what|how|why|which|when|where)\b"], 0.65),
]


def route(text: str, verified: bool = False, language: Optional[str] = None) -> RouteDecision:
    t = normalize(text)
    lang = language or detect_language(t)

    best: Tuple[Intent, float] = (Intent.UNKNOWN, 0.3)
    for intent, patterns, confidence in _RULES:
        if any(re.search(p, t) for p in patterns):
            best = (intent, confidence)
            break

    intent, confidence = best
    mode = INTENT_DEFAULT_MODE[intent]
    requires_identity = intent in GATED_INTENTS and not verified

    if confidence < CONFIDENCE_THRESHOLD:
        intent, mode = Intent.UNKNOWN, Mode.GENERATED

    return RouteDecision(
        intent=intent,
        agent=INTENT_AGENT[intent],
        mode=mode,
        confidence=confidence,
        language=lang,
        requires_identity=requires_identity,
    )
