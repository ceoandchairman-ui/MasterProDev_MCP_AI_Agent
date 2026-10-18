"""Cache keys and the rules for what may be cached."""

import hashlib
import re
from typing import Optional

from mpd_assistant.privacy.detector import detect
from mpd_assistant.routing.intents import Intent, Mode

_TOKEN_RE = re.compile(r"<[A-Z_]+_\d+>")
SHAREABLE_INTENTS = frozenset({Intent.FAQ, Intent.KNOWLEDGE_QUESTION, Intent.GREETING})


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", (text or "").lower())).strip()


def build_key(
    *,
    tenant: str,
    locale: str,
    mode: Mode,
    agent: str,
    query: str,
    prompt_version: str,
    corpus_version: str,
    user_id: Optional[str] = None,
) -> str:
    scope = f"user:{user_id}" if user_id else "shared"
    digest = hashlib.sha256(normalize_query(query).encode()).hexdigest()[:32]
    return f"resp:{tenant}:{locale}:{mode.value}:{agent}:{prompt_version}:{corpus_version}:{scope}:{digest}"


def may_cache(*, intent: Intent, query: str, response: str, evaluator_passed: bool, used_side_effect_tool: bool) -> bool:
    """Evaluator-gated writes; never cache side effects or anything containing personal data."""
    if not evaluator_passed or used_side_effect_tool:
        return False
    if intent not in SHAREABLE_INTENTS:
        return False
    if _TOKEN_RE.search(query) or _TOKEN_RE.search(response):
        return False  # privacy tokens are session-specific; a shared entry would resolve to the wrong person
    return not detect(query) and not detect(response)
