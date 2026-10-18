"""Offline evaluation: golden routing and retrieval sets, a JSON report, metrics, and optional Ragas scores."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from mpd_assistant.observability.metrics import EVAL_SCORE
from mpd_assistant.retrieval.hybrid import ground
from mpd_assistant.routing.router import route

THRESHOLDS = {
    "routing": {"accuracy": (">=", 0.90)},
    "retrieval": {"hit_rate": (">=", 0.80), "refusal_rate": (">=", 0.90)},
}


def _load(path: Path) -> List[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["cases"]


def run_routing(path: Path) -> Dict[str, Any]:
    cases = _load(path)
    failures = []
    for case in cases:
        decision = route(case["text"], verified=case["verified"])
        expected = case["intent"]
        ok = (decision.intent.value == expected and decision.agent.value == case["agent"]) if expected != "unknown" else (
            decision.intent.value in ("unknown", "knowledge_question") or decision.confidence < 0.6
        )
        if not ok:
            failures.append({"id": case["id"], "expected": expected, "got": decision.intent.value})
    return {"suite": "routing", "cases": len(cases), "accuracy": 1 - len(failures) / len(cases), "failures": failures}


async def run_retrieval(path: Path, retriever, min_score: float, top_k: int = 3) -> Dict[str, Any]:
    cases = _load(path)
    hit, hits_total, refused, refusals_total, failures = 0, 0, 0, 0, []
    for case in cases:
        results = await retriever.search(case["question"])
        if case["expect"] is None:
            refusals_total += 1
            if not ground(results, min_score=min_score).answerable:
                refused += 1
            else:
                failures.append({"id": case["id"], "problem": "answered an off-topic question"})
        else:
            hits_total += 1
            if case["expect"] in [h.source for h in results[:top_k]]:
                hit += 1
            else:
                failures.append({"id": case["id"], "problem": f"{case['expect']} not in top {top_k}"})
    return {
        "suite": "retrieval",
        "cases": len(cases),
        "hit_rate": hit / hits_total if hits_total else 1.0,
        "refusal_rate": refused / refusals_total if refusals_total else 1.0,
        "failures": failures,
    }


def ragas_scores(samples: List[Dict[str, Any]], llm=None, embeddings=None) -> Optional[Dict[str, float]]:
    """Faithfulness, answer relevancy and context precision/recall via Ragas. Returns None when Ragas or a judge
    model is unavailable, so offline runs never fail just because the optional dependency is missing."""
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
    except ImportError:
        return None
    if llm is None:
        return None
    result = evaluate(Dataset.from_list(samples), metrics=[faithfulness, answer_relevancy, context_precision, context_recall], llm=llm, embeddings=embeddings)
    return {k: float(v) for k, v in dict(result).items()}


def failures_against_thresholds(report: Dict[str, Any]) -> List[str]:
    out = []
    for metric, (op, limit) in THRESHOLDS.get(report["suite"], {}).items():
        value = report.get(metric)
        if value is None:
            continue
        if (value < limit) if op == ">=" else (value > limit):
            out.append(f"{report['suite']}.{metric}={value:.2f} (needs {op} {limit})")
    return out


def publish(report: Dict[str, Any]) -> None:
    for metric in ("accuracy", "hit_rate", "refusal_rate"):
        if metric in report:
            EVAL_SCORE.labels(report["suite"], metric).set(report[metric])


def write_report(reports: List[Dict[str, Any]], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"eval-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps({"reports": reports, "failed": [f for r in reports for f in failures_against_thresholds(r)]}, indent=2), encoding="utf-8")
    return path
