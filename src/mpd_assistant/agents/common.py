"""Shared agent helpers: robust JSON parsing, plan validation, confirmation detection."""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

_AFFIRM = {"yes", "y", "yep", "yeah", "sure", "ok", "okay", "confirm", "confirmed", "go ahead", "please do", "do it", "oui", "d'accord", "confirme", "vas-y"}
_NEGATE = {"no", "n", "nope", "cancel", "stop", "don't", "do not", "non", "annule", "annuler"}


def is_affirmative(text: str) -> bool:
    t = re.sub(r"[^\w' ]", "", (text or "").lower()).strip()
    return t in _AFFIRM or any(t.startswith(a + " ") for a in ("yes", "oui", "confirm", "sure", "go ahead"))


def is_negative(text: str) -> bool:
    t = re.sub(r"[^\w' ]", "", (text or "").lower()).strip()
    return t in _NEGATE or any(t.startswith(n + " ") for n in ("no", "non", "cancel", "stop"))


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from model output (handles code fences and prose around it)."""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", text)
    start = cleaned.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(cleaned)):
            depth += (cleaned[i] == "{") - (cleaned[i] == "}")
            if depth == 0:
                try:
                    obj = json.loads(cleaned[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    break
        start = cleaned.find("{", start + 1)
    return None


@dataclass(frozen=True)
class PlanStep:
    tool: str
    args: Dict[str, Any]


def parse_plan(text: str, allowed_tools: Iterable[str], max_steps: int = 4) -> List[PlanStep]:
    """Only steps naming an allowed tool with dict arguments survive; everything else is dropped."""
    obj = parse_json_object(text) or {}
    allowed = set(allowed_tools)
    steps = []
    for raw in obj.get("steps", [])[:max_steps] if isinstance(obj.get("steps"), list) else []:
        if isinstance(raw, dict) and raw.get("tool") in allowed and isinstance(raw.get("args", {}), dict):
            steps.append(PlanStep(raw["tool"], raw.get("args", {})))
    return steps
