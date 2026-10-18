from pathlib import Path

import pytest
import yaml

from mpd_assistant.routing.intents import Intent
from mpd_assistant.routing.router import route

GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "datasets" / "routing_golden.yaml"
CASES = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", [pytest.param(c, id=c["id"]) for c in CASES])
def test_routing_golden(case):
    decision = route(case["text"], verified=case["verified"])
    expected_intent = case["intent"]
    if expected_intent == "unknown":
        assert decision.intent in (Intent.UNKNOWN, Intent.KNOWLEDGE_QUESTION) or decision.confidence < 0.6
    else:
        assert decision.intent.value == expected_intent, f"{case['id']}: got {decision.intent.value}"
        assert decision.agent.value == case["agent"]
    if case.get("gated"):
        assert decision.requires_identity
