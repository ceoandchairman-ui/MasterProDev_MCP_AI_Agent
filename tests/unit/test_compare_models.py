"""The model comparison script: its cases, its checks (they must accept good answers and reject bad ones), and its reporting."""

import argparse
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mpd_assistant.core.llm.client import LLMError, LLMResult

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compare_models.py"
spec = importlib.util.spec_from_file_location("compare_models", SCRIPT)
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)

PLAN = json.dumps({"steps": [{"tool": "create_calendar_event", "args": {"title": "Discovery call", "start_time": "2026-11-03T14:00:00", "end_time": "2026-11-03T14:30:00"}}]})
SCOPE = json.dumps({"summary": "A booking app.", "milestones": [{"name": "Discovery", "weeks": 2}, {"name": "Build", "weeks": 10}, {"name": "Launch", "weeks": 2}], "assumptions": ["API exists"], "risks": ["Scope creep"]})


class Scripted:
    """Answers each task the way a good model would; `broken` models answer nonsense or fail."""

    def __init__(self, model="good-model", mode="good"):
        self.model, self.mode = model, mode

    async def complete(self, messages, *, tier="mid", max_tokens=512, temperature=0.0):
        if self.mode == "down":
            raise LLMError("down", status=503)
        system, user = messages[0]["content"], messages[-1]["content"]
        if self.mode == "bad":
            return LLMResult("I am sorry, I cannot help with that.", tokens_out=7)
        if "strict fact checker" in system:
            return LLMResult(json.dumps({"supported": 0.05 if "Paris" in user else 0.95, "issues": []}), tokens_out=20)
        if "Extract project details" in system:
            return LLMResult(json.dumps({"need": "booking app", "timeline": "March", "budget": "40k", "company": "Acme Logistics"}), tokens_out=30)
        if "standalone question" in system:
            return LLMResult('"How long does it take to build a mobile app?"\nI resolved "it".', tokens_out=12)
        if "plan calendar and email actions" in system:
            return LLMResult(PLAN, tokens_out=60)
        if "Answer ONLY from the provided context" in system:
            return LLMResult("Nous construisons des applications mobiles pour les entreprises de logistique.", tokens_out=25)
        return LLMResult(SCOPE, tokens_out=300)


def factory(mode_by_model):
    return lambda model: Scripted(model, mode_by_model.get(model, "good"))


# --- the cases ----------------------------------------------------------------------------------
def test_there_are_cases_for_every_tier_with_real_prompts():
    cases = cm.build_cases()
    assert {c.tier for c in cases} == {"cheap", "mid", "reasoning"} and len({c.name for c in cases}) == len(cases)
    planner = next(c for c in cases if c.name == "plan a booking")
    assert "create_calendar_event(title: str" in planner.messages[0]["content"]  # the argument schemas are in the prompt
    assert next(c for c in cases if c.tier == "reasoning").max_tokens == 900  # the budget the Solution Architect really has


async def test_a_good_model_passes_every_case():
    outcomes = await cm.evaluate({"cheap": ["good-model"], "mid": ["good-model"], "reasoning": ["good-model"]}, factory({}))
    failed = [(o.case, o.note) for o in outcomes if not o.ok]
    assert failed == [] and len(outcomes) == len(cm.build_cases())


async def test_a_model_that_answers_nonsense_fails_every_case():
    outcomes = await cm.evaluate({"cheap": ["bad"], "mid": ["bad"], "reasoning": ["bad"]}, factory({"bad": "bad"}))
    assert outcomes and not any(o.ok for o in outcomes)


async def test_a_model_that_is_down_is_reported_with_its_status_not_a_crash():
    outcomes = await cm.evaluate({"mid": ["down"]}, factory({"down": "down"}))
    assert outcomes and all(not o.ok and o.note == "call failed (HTTP 503)" and o.tokens_out == 0 for o in outcomes)


# --- the checks themselves --------------------------------------------------------------------
def test_slot_check_needs_all_four_values():
    assert cm.check_slots(json.dumps({"need": "x", "timeline": "y", "budget": "z", "company": "c"}))[0]
    assert not cm.check_slots(json.dumps({"need": "x", "timeline": None, "budget": "z", "company": "c"}))[0]
    assert not cm.check_slots("no json here")[0]


def test_plan_check_requires_the_right_tool_with_valid_arguments():
    assert cm.check_plan(PLAN)[0]
    assert not cm.check_plan(json.dumps({"steps": [{"tool": "send_email", "args": {}}]}))[0]
    missing_end = json.dumps({"steps": [{"tool": "create_calendar_event", "args": {"title": "x", "start_time": "2026-11-03T14:00:00"}}]})
    ok, note = cm.check_plan(missing_end)
    assert not ok and "end_time is required" in note
    assert not cm.check_plan(json.dumps({"steps": []}))[0]


def test_french_check_rejects_english():
    assert cm.check_french("Nous construisons des applications mobiles.")[0]
    assert not cm.check_french("We build custom mobile apps for logistics.")[0]
    assert not cm.check_french("Software development.")[0]


def test_rewrite_check_wants_one_clean_topical_line():
    assert cm.check_rewrite("How long does a mobile app take?")[0]
    assert not cm.check_rewrite("How long does it take?")[0]  # lost the topic
    assert not cm.check_rewrite('{"question": "mobile app timeline"}')[0]
    assert not cm.check_rewrite("")[0]


def test_scope_check_catches_truncated_and_thin_output():
    assert cm.check_scope(SCOPE)[0]
    ok, note = cm.check_scope(SCOPE[:-40])  # cut off mid-way: the failure the 900-token limit caused with one candidate
    assert not ok and "no complete scope" in note
    assert not cm.check_scope(json.dumps({"summary": "x", "milestones": [{"name": "only one"}], "risks": ["r"]}))[0]


def test_judge_check_depends_on_what_is_expected():
    assert cm.judge_check(True)('{"supported": 0.9}')[0] and not cm.judge_check(True)('{"supported": 0.3}')[0]
    assert cm.judge_check(False)('{"supported": 0.1}')[0] and not cm.judge_check(False)('{"supported": 0.8}')[0]
    assert not cm.judge_check(True)("not a score")[0] and not cm.judge_check(True)('{"supported": "high"}')[0]


# --- reporting ----------------------------------------------------------------------------------
async def test_models_are_ranked_by_pass_rate_then_speed():
    outcomes = await cm.evaluate({"reasoning": ["good-model", "bad", "down"]}, factory({"bad": "bad", "down": "down"}), runs=2)
    rows = cm.summarize(outcomes)
    assert [r["model"] for r in rows][0] == "good-model" and rows[0]["passed"] == rows[0]["total"] == 4  # 2 scope cases x 2 runs
    assert {r["model"] for r in rows} == {"good-model", "bad", "down"} and rows[-1]["passed"] == 0
    table = cm.render_table(rows)
    assert "good-model" in table and "4/4" in table and "0/4" in table
    failures = cm.render_failures(outcomes)
    assert "FAIL reasoning/bad" in failures and "call failed (HTTP 503)" in failures and "good-model" not in failures


def test_an_empty_run_says_so():
    assert cm.render_table([]) == "nothing to compare" and cm.summarize([]) == []


def test_planning_the_models_for_each_tier():
    settings = SimpleNamespace(HUGGINGFACE_MODEL="mid-m", LLM_MODEL_CHEAP="cheap-m", LLM_MODEL_REASONING=None)
    current = cm.plan_models(argparse.Namespace(tier="all", current=True, models=None), settings)
    assert current == {"cheap": ["cheap-m"], "mid": ["mid-m"], "reasoning": ["mid-m"]}  # an unset tier shares the mid model
    chosen = cm.plan_models(argparse.Namespace(tier="reasoning", current=False, models="a, b ,c"), settings)
    assert chosen == {"reasoning": ["a", "b", "c"]}
    with pytest.raises(SystemExit):
        cm.plan_models(argparse.Namespace(tier="mid", current=False, models=""), settings)
