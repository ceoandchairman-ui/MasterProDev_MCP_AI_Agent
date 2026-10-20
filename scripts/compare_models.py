"""Runs the project's real prompts through candidate models and prints a pass rate, speed and size per model, so choosing the
model for a tier is a measurement instead of a guess. Each case is a task one of the agents actually performs.

    python scripts/compare_models.py --current                       # the models configured in .env for each tier
    python scripts/compare_models.py --tier reasoning --models moonshotai/Kimi-K2-Instruct-0905,meta-llama/Llama-3.3-70B-Instruct --runs 3
    python scripts/compare_models.py --tier cheap --models meta-llama/Llama-3.1-8B-Instruct --json results.json

It makes real, billed model calls (a few cents for a full run), using LLM_BASE_URL and HUGGINGFACE_API_KEY from the settings.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Tuple

from mpd_assistant.agents.common import parse_json_object
from mpd_assistant.agents.prompts import load_prompt
from mpd_assistant.core.llm.client import TIERS, LLMError
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.registry import Role, default_registry

REGISTRY = default_registry()
Check = Callable[[str], Tuple[bool, str]]


@dataclass(frozen=True)
class Case:
    name: str
    tier: str
    messages: List[Dict[str, str]]
    max_tokens: int
    check: Check


@dataclass
class Outcome:
    model: str
    tier: str
    case: str
    ok: bool
    seconds: float
    tokens_out: int
    note: str


# --- checks: each returns (passed, short reason) ----------------------------------------------
def check_slots(text: str) -> Tuple[bool, str]:
    data = parse_json_object(text) or {}
    ok = bool(data.get("budget")) and bool(data.get("company")) and bool(data.get("timeline")) and bool(data.get("need"))
    return ok, f"keys with values: {sorted(k for k, v in data.items() if v)}"


def check_plan(text: str) -> Tuple[bool, str]:
    data = parse_json_object(text) or {}
    steps = data.get("steps") or []
    if not steps or steps[0].get("tool") != "create_calendar_event":
        return False, f"tools: {[s.get('tool') for s in steps]}"
    problems = REGISTRY.validate_args("create_calendar_event", steps[0].get("args", {}))
    return not problems, f"argument problems: {problems}" if problems else "valid arguments"


def check_french(text: str) -> Tuple[bool, str]:
    lowered = f" {text.lower()} "
    french = any(w in lowered for w in (" nous ", " vous ", " notre ", " nos ", " des ", " les "))
    english = " we build " in lowered or " our team " in lowered
    return french and not english, "French reply" if french and not english else "not clearly French"


def check_rewrite(text: str) -> Tuple[bool, str]:
    line = text.strip().splitlines()[0] if text.strip() else ""
    ok = "mobile" in line.lower() and "{" not in line and 0 < len(line) <= 300
    return ok, f"rewrote to: {line[:80]!r}"


def check_scope(text: str) -> Tuple[bool, str]:
    data = parse_json_object(text) or {}
    if not data.get("summary"):  # truncated output often parses as just an inner object, such as one milestone
        return False, "no complete scope (truncated or empty)"
    milestones = data.get("milestones") or []
    ok = len(milestones) >= 3 and all(isinstance(m, dict) and m.get("name") for m in milestones) and bool(data.get("risks"))
    return ok, f"{len(milestones)} milestones, {len(data.get('risks') or [])} risks"


def judge_check(expect_supported: bool) -> Check:
    def check(text: str) -> Tuple[bool, str]:
        data = parse_json_object(text) or {}
        try:
            score = float(data["supported"])
        except (KeyError, TypeError, ValueError):
            return False, "no numeric score"
        ok = score >= 0.7 if expect_supported else score <= 0.4
        return ok, f"score {score:.2f}"

    return check


def _msgs(system: str, user: str) -> List[Dict[str, str]]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_cases() -> List[Case]:
    evidence = "[1] MasterProDev builds custom mobile apps and web platforms for logistics and retail companies from its Toronto office."
    scope_prompt = load_prompt("solution_architect", "system").render(language="en")
    scopes = [
        "Requirements: a booking mobile app for a logistics firm with driver tracking, customer notifications and an admin dashboard. Existing REST API. Launch in 4 months.",
        "Requirements: an online store for a retail chain with ERP inventory sync, loyalty points, English and French, and Stripe payments. Launch before the holidays.",
    ]
    cases = [
        Case("slot extraction", "cheap", _msgs(load_prompt("lead_conversion", "extract").render(), "We're Acme Logistics and need a booking app live by March, budget around 40k."), 200, check_slots),
        Case(
            "follow-up rewrite", "cheap",
            _msgs(load_prompt("concierge", "rewrite").render(), "Conversation so far:\nuser: What mobile apps do you build?\nassistant: Custom mobile apps for logistics firms.\n\nLatest message: And how long does it take?"),
            80, check_rewrite,
        ),
        Case(
            "judge: supported answer", "mid",
            _msgs(load_prompt("evaluator", "judge").render(), f"EVIDENCE:\n{evidence}\n\nANSWER:\nMasterProDev builds mobile apps for logistics companies."), 120, judge_check(True),
        ),
        Case(
            "judge: unsupported answer", "mid",
            _msgs(load_prompt("evaluator", "judge").render(), f"EVIDENCE:\n{evidence}\n\nANSWER:\nMasterProDev has offices in Paris and Berlin and builds video games."), 120, judge_check(False),
        ),
        Case(
            "plan a booking", "mid",
            _msgs(
                load_prompt("comms_scheduling", "planner").render(tools=REGISTRY.describe(Agent.COMMS_SCHEDULING, Role.VERIFIED)),
                "Book a 30 minute discovery call on 2026-11-03 at 2pm Toronto time titled Discovery call",
            ),
            300, check_plan,
        ),
        Case("grounded French answer", "mid", _msgs(load_prompt("concierge", "system").render(language="fr"), f"Context:\n{evidence}\n\nQuestion: Que construisez-vous ?"), 400, check_french),
    ]
    cases += [Case(f"scope JSON #{i + 1}", "reasoning", _msgs(scope_prompt, text), 900, check_scope) for i, text in enumerate(scopes)]
    return cases


# --- running ------------------------------------------------------------------------------------
async def run_case(llm: Any, model: str, case: Case) -> Outcome:
    started = time.perf_counter()
    try:
        result = await llm.complete(case.messages, tier=case.tier, max_tokens=case.max_tokens, temperature=0.0)
    except LLMError as exc:
        status = f" (HTTP {exc.status})" if getattr(exc, "status", None) else ""
        return Outcome(model, case.tier, case.name, False, time.perf_counter() - started, 0, f"call failed{status}")
    ok, note = case.check(result.text)
    return Outcome(model, case.tier, case.name, ok, time.perf_counter() - started, result.tokens_out, note)


async def evaluate(models_by_tier: Dict[str, List[str]], make_llm: Callable[[str], Any], runs: int = 1, cases: List[Case] | None = None) -> List[Outcome]:
    cases = cases if cases is not None else build_cases()
    outcomes: List[Outcome] = []
    for tier, models in models_by_tier.items():
        for model in models:
            llm = make_llm(model)
            for case in (c for c in cases if c.tier == tier):
                for _ in range(max(1, runs)):
                    outcomes.append(await run_case(llm, model, case))
    return outcomes


def summarize(outcomes: List[Outcome]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], List[Outcome]] = {}
    for o in outcomes:
        groups.setdefault((o.tier, o.model), []).append(o)
    rows = []
    for (tier, model), items in groups.items():
        rows.append(
            {
                "tier": tier, "model": model, "passed": sum(o.ok for o in items), "total": len(items),
                "avg_seconds": round(statistics.mean(o.seconds for o in items), 1), "avg_tokens_out": round(statistics.mean(o.tokens_out for o in items)),
            }
        )
    return sorted(rows, key=lambda r: (r["tier"], -r["passed"] / r["total"], r["avg_seconds"]))


def render_table(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "nothing to compare"
    width = max(len(r["model"]) for r in rows)
    lines = [f"{'tier':10} {'model'.ljust(width)}  pass   avg time  avg tokens out"]
    for r in rows:
        lines.append(f"{r['tier']:10} {r['model'].ljust(width)}  {r['passed']}/{r['total']}".ljust(10 + width + 12) + f"  {r['avg_seconds']:6.1f}s  {r['avg_tokens_out']:>8}")
    return "\n".join(lines)


def render_failures(outcomes: List[Outcome]) -> str:
    return "\n".join(f"  FAIL {o.tier}/{o.model} - {o.case}: {o.note}" for o in outcomes if not o.ok)


def plan_models(args: argparse.Namespace, settings) -> Dict[str, List[str]]:
    tiers = list(TIERS) if args.tier == "all" else [args.tier]
    if args.current:
        configured = {"mid": settings.HUGGINGFACE_MODEL, "cheap": settings.LLM_MODEL_CHEAP or settings.HUGGINGFACE_MODEL, "reasoning": settings.LLM_MODEL_REASONING or settings.HUGGINGFACE_MODEL}
        return {t: [configured[t]] for t in tiers if configured[t]}
    models = [m.strip() for m in (args.models or "").split(",") if m.strip()]
    if not models:
        raise SystemExit("Give --models a,b,c or use --current")
    return {t: models for t in tiers}


async def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tier", choices=[*TIERS, "all"], default="all")
    parser.add_argument("--models", help="comma-separated model names to try for the chosen tier(s)")
    parser.add_argument("--current", action="store_true", help="use the models configured for each tier")
    parser.add_argument("--runs", type=int, default=1, help="repeat each case this many times")
    parser.add_argument("--json", help="also write the results to this file")
    args = parser.parse_args(argv)

    from mpd_assistant.core.config import get_settings
    from mpd_assistant.core.llm.client import OpenAICompatibleLLM

    settings = get_settings()
    if not settings.HUGGINGFACE_API_KEY:
        raise SystemExit("Set HUGGINGFACE_API_KEY (and LLM_BASE_URL if not using the HuggingFace router)")
    plan = plan_models(args, settings)

    def make_llm(model: str):
        return OpenAICompatibleLLM(settings.LLM_BASE_URL, settings.HUGGINGFACE_API_KEY, {t: model for t in TIERS}, timeout=90.0, retries=1)

    outcomes = await evaluate(plan, make_llm, args.runs)
    print(render_table(summarize(outcomes)))
    failures = render_failures(outcomes)
    if failures:
        print("\nFailures:\n" + failures)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": summarize(outcomes), "outcomes": [asdict(o) for o in outcomes]}, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
