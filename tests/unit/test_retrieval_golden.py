"""Golden retrieval checks: every expected document must rank in the top results, and off-topic questions must not
clear the grounding threshold. Uses the deterministic test embedder, so it guards the pipeline, not model quality;
run `scripts/eval_retrieval.py` against the real embedder before changing RETRIEVAL_MIN_SCORE."""

from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from mpd_assistant.core.db import ensure_tenant
from mpd_assistant.core.models import Base
from mpd_assistant.ingestion.indexer import index_document
from mpd_assistant.retrieval.embeddings import HashEmbedder
from mpd_assistant.retrieval.hybrid import ground
from mpd_assistant.retrieval.pg import PgRetriever
from tests.unit.test_knowledge_retrieval import DIM, DOCS

GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "datasets" / "retrieval_golden.yaml"
TOP_K = 3
MIN_SCORE = 0.35


@pytest.fixture
async def retriever():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    tenant = ensure_tenant(engine)
    for name, text in DOCS.items():
        await index_document(engine, tenant, name, text, HashEmbedder(DIM), expected_dim=DIM)
    return PgRetriever(engine, tenant, HashEmbedder(DIM), top_k=TOP_K)


def cases():
    data = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    return [pytest.param(c, id=c["id"]) for c in data["cases"]]


@pytest.mark.parametrize("case", cases())
async def test_golden_case(retriever, case):
    hits = await retriever.search(case["question"])
    if case["expect"] is None:
        assert not ground(hits, min_score=MIN_SCORE).answerable, "off-topic question must not be grounded"
    else:
        assert case["expect"] in [h.source for h in hits[:TOP_K]], f"{case['expect']} not in top {TOP_K}"
