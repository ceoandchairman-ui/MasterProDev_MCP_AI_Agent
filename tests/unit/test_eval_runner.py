import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from mpd_assistant.core.db import ensure_tenant
from mpd_assistant.core.models import Base
from mpd_assistant.evaluation.offline.runner import (
    failures_against_thresholds,
    publish,
    ragas_scores,
    run_retrieval,
    run_routing,
    write_report,
)
from mpd_assistant.ingestion.indexer import index_document
from mpd_assistant.observability import metrics
from mpd_assistant.retrieval.embeddings import HashEmbedder
from mpd_assistant.retrieval.pg import PgRetriever
from tests.unit.test_knowledge_retrieval import DIM, DOCS

ROOT = Path(__file__).resolve().parents[2]


def test_routing_suite_meets_its_threshold_on_the_shipped_golden_set():
    report = run_routing(ROOT / "evals/datasets/routing_golden.yaml")
    assert report["accuracy"] >= 0.9 and failures_against_thresholds(report) == []


async def test_retrieval_suite_reports_hit_and_refusal_rates():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    tenant = ensure_tenant(engine)
    for name, text in DOCS.items():
        await index_document(engine, tenant, name, text, HashEmbedder(DIM), expected_dim=DIM)
    retriever = PgRetriever(engine, tenant, HashEmbedder(DIM))
    report = await run_retrieval(ROOT / "evals/datasets/retrieval_golden.yaml", retriever, min_score=0.35)
    assert report["hit_rate"] >= 0.8 and report["refusal_rate"] == 1.0


def test_threshold_failures_are_named():
    bad = {"suite": "retrieval", "hit_rate": 0.5, "refusal_rate": 1.0, "failures": []}
    assert failures_against_thresholds(bad) == ["retrieval.hit_rate=0.50 (needs >= 0.8)"]


def test_report_is_written_and_scores_are_published(tmp_path):
    reports = [{"suite": "routing", "cases": 2, "accuracy": 0.5, "failures": [{"id": "x"}]}]
    publish(reports[0])
    assert metrics.EVAL_SCORE.labels("routing", "accuracy")._value.get() == 0.5
    path = write_report(reports, tmp_path / "reports")
    data = json.loads(path.read_text())
    assert data["failed"] and data["reports"][0]["suite"] == "routing"


def test_ragas_is_optional():
    assert ragas_scores([{"question": "q"}], llm=None) is None
