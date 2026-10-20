"""Run the golden evaluations and write a report. Exits non-zero when a threshold is missed.

  python scripts/run_evals.py             routing only (no services needed)
  python scripts/run_evals.py --retrieval retrieval against the configured database and embedding endpoint
  python scripts/run_evals.py --memory    memory recall (add --embeddings for the cross-language cases)

Run the retrieval suite against the real embedder before changing RETRIEVAL_MIN_SCORE or RERANK_MIN_SCORE.
"""

import asyncio
import sys
from pathlib import Path

from mpd_assistant.core.config import get_settings
from mpd_assistant.core.db import ensure_tenant, make_engine
from mpd_assistant.evaluation.offline.memory_eval import run_memory
from mpd_assistant.evaluation.offline.runner import (
    failures_against_thresholds,
    publish,
    run_retrieval,
    run_routing,
    write_report,
)
from mpd_assistant.retrieval.embeddings import OpenAICompatibleEmbedder
from mpd_assistant.retrieval.pg import PgRetriever

ROOT = Path(__file__).resolve().parents[1]


async def main() -> int:
    reports = [run_routing(ROOT / "evals/datasets/routing_golden.yaml")]
    if "--retrieval" in sys.argv:
        s = get_settings()
        key = s.EMBEDDING_API_KEY or s.HUGGINGFACE_API_KEY
        if not key:
            raise SystemExit("Set EMBEDDING_API_KEY or HUGGINGFACE_API_KEY for the retrieval suite")
        engine = make_engine(s.DATABASE_URL)
        retriever = PgRetriever(engine, ensure_tenant(engine), OpenAICompatibleEmbedder(s.EMBEDDING_BASE_URL or s.LLM_BASE_URL, key, s.EMBEDDING_MODEL))
        reports.append(await run_retrieval(ROOT / "evals/datasets/retrieval_golden.yaml", retriever, s.RETRIEVAL_MIN_SCORE))
    if "--memory" in sys.argv:
        embedder = None
        if "--embeddings" in sys.argv:
            s = get_settings()
            key = s.EMBEDDING_API_KEY or s.HUGGINGFACE_API_KEY
            if not key:
                raise SystemExit("Set EMBEDDING_API_KEY or HUGGINGFACE_API_KEY for --embeddings")
            embedder = OpenAICompatibleEmbedder(s.EMBEDDING_BASE_URL or s.LLM_BASE_URL, key, s.EMBEDDING_MODEL)
        reports.append(await run_memory(ROOT / "evals/datasets/memory_golden.yaml", embedder))
    for report in reports:
        publish(report)
        print({k: v for k, v in report.items() if k != "failures"})
        for failure in report["failures"]:
            print("  -", failure)
    path = write_report(reports, ROOT / "evals" / "reports")
    failed = [f for r in reports for f in failures_against_thresholds(r)]
    print(f"report: {path}")
    for f in failed:
        print("THRESHOLD MISSED:", f)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
