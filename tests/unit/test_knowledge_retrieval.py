import httpx
import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.pool import StaticPool

from mpd_assistant.agents.factory import build_runners
from mpd_assistant.core import crypto
from mpd_assistant.core.db import ensure_tenant
from mpd_assistant.core.llm.client import FakeLLM
from mpd_assistant.core.models import Base, DocumentChunk, Tenant
from mpd_assistant.graph.builder import build_graph
from mpd_assistant.graph.service import ChatService
from mpd_assistant.ingestion.chunker import chunk_text
from mpd_assistant.ingestion.indexer import IndexError_, index_directory, index_document
from mpd_assistant.privacy.vault import MemoryVaultStore, PiiVault
from mpd_assistant.retrieval.bm25 import Bm25Index, tokenize
from mpd_assistant.retrieval.embeddings import EmbeddingError, HashEmbedder, OpenAICompatibleEmbedder
from mpd_assistant.retrieval.pg import PgRetriever
from mpd_assistant.tools.registry import default_registry

DIM = 64
DOCS = {
    "services.txt": "MasterProDev builds custom mobile apps and web platforms for logistics and retail companies.\n\n"
    "We also provide architecture audits, cloud migration and ongoing maintenance.",
    "contact.txt": "Our Toronto office is open Monday to Friday. You can book a discovery call through the assistant.\n\n"
    "Pricing depends on scope and is quoted after a short discovery conversation with our team.",
    "equipe.txt": "Notre équipe développe des applications mobiles et des plateformes web sur mesure.",
}


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return eng


async def seed(engine, docs=DOCS, tenant=None):
    tenant = tenant or ensure_tenant(engine)
    for name, text in docs.items():
        await index_document(engine, tenant, name, text, HashEmbedder(DIM), expected_dim=DIM)
    return tenant


# --- chunker ---------------------------------------------------------------
def test_chunker_respects_size_overlap_and_paragraphs():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(8))
    chunks = chunk_text(text, target=500, overlap=80)
    assert len(chunks) > 1 and all(len(c) <= 500 + 80 + 4 for c in chunks)
    assert chunks[0][-40:].strip() in chunks[1]  # overlap carries context forward


def test_chunker_handles_giant_sentence_and_tiny_text():
    assert all(len(c) <= 300 for c in chunk_text("x" * 2000, target=300, overlap=0))
    assert chunk_text("Short but valid text that is long enough to keep.") != []
    assert chunk_text("   ") == []


# --- bm25 ------------------------------------------------------------------------
def test_tokenizer_folds_accents_and_drops_stopwords():
    assert tokenize("L'équipe de développement") == ["equipe", "developpement"]
    assert "the" not in tokenize("the quick fox")


def test_bm25_ranks_exact_terms_and_ignores_unknown_words():
    index = Bm25Index([("a", "cloud migration services"), ("b", "mobile app development"), ("c", "pricing and quotes")])
    assert index.search("mobile app")[0][0] == "b"
    assert index.search("zzzz") == [] and index.search("the of") == []
    assert [d for d, _ in index.search("equipe")] == []
    assert Bm25Index([]).search("anything") == []


def test_bm25_returns_only_documents_that_contain_a_query_term():
    index = Bm25Index([("a", "mobile app development"), ("b", "pricing and quotes"), ("c", "cloud migration")])
    assert [d for d, _ in index.search("mobile pricing")] in (['a', 'b'], ['b', 'a'])


def test_bm25_matches_accented_and_plain_forms():
    index = Bm25Index([("fr", "Notre équipe développe des applications"), ("en", "pricing quotes")])
    assert index.search("equipe applications")[0][0] == "fr"


# --- embeddings client ----------------------------------------------------------------
async def test_embedder_batches_orders_and_hides_key():
    calls = []

    def handler(request):
        import json

        body = json.loads(request.content)
        calls.append(len(body["input"]))
        data = [{"index": i, "embedding": [float(len(t))]} for i, t in reversed(list(enumerate(body["input"])))]
        return httpx.Response(200, json={"data": data})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    emb = OpenAICompatibleEmbedder("https://x/v1", "k", "bge", client=client)
    texts = ["a" * (i + 1) for i in range(70)]
    vectors = await emb.embed(texts)
    assert calls == [32, 32, 6] and [v[0] for v in vectors] == [float(i + 1) for i in range(70)]

    bad = OpenAICompatibleEmbedder("https://x/v1", "SECRET", "m", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(EmbeddingError) as exc:
        await bad.embed(["x"])
    assert "SECRET" not in str(exc.value)


# --- indexer ---------------------------------------------------------------------------------
async def test_index_is_idempotent_and_replaces_changed_documents(engine):
    tenant = ensure_tenant(engine)
    assert await index_document(engine, tenant, "a.txt", DOCS["services.txt"], HashEmbedder(DIM), DIM) == "indexed"
    assert await index_document(engine, tenant, "a.txt", DOCS["services.txt"], HashEmbedder(DIM), DIM) == "unchanged"
    assert await index_document(engine, tenant, "a.txt", "Completely different content about security audits.", HashEmbedder(DIM), DIM) == "indexed"
    with DbSession(engine) as db:
        texts = list(db.scalars(select(DocumentChunk.text)))
    assert len(texts) == 1 and "security audits" in texts[0]


async def test_dimension_mismatch_is_rejected_before_writing(engine):
    tenant = ensure_tenant(engine)
    with pytest.raises(IndexError_):
        await index_document(engine, tenant, "a.txt", "Some long enough document text for chunking.", HashEmbedder(8), expected_dim=DIM)
    with DbSession(engine) as db:
        assert db.scalar(select(func.count(DocumentChunk.id))) == 0


async def test_index_directory_skips_temp_files_and_reports_failures(engine, tmp_path):
    (tmp_path / "ok.md").write_text("A valid markdown knowledge document about services.", encoding="utf-8")
    (tmp_path / "~$lock.docx").write_text("x")
    (tmp_path / "image.png").write_bytes(b"x")
    (tmp_path / "broken.docx").write_bytes(b"not a real docx")
    results = await index_directory(engine, ensure_tenant(engine), tmp_path, HashEmbedder(DIM), DIM)
    assert results["ok.md"] == "indexed" and results["broken.docx"].startswith("failed:")
    assert "~$lock.docx" not in results and "image.png" not in results


# --- retriever ---------------------------------------------------------------------------------------
async def test_hybrid_search_finds_the_relevant_document(engine):
    tenant = await seed(engine)
    hits = await PgRetriever(engine, tenant, HashEmbedder(DIM)).search("mobile apps for logistics")
    assert hits[0].source == "services.txt" and hits[0].score > 0.3


async def test_bm25_side_rescues_exact_keyword_and_french_documents(engine):
    tenant = await seed(engine)
    hits = await PgRetriever(engine, tenant, HashEmbedder(DIM)).search("equipe applications mobiles")
    assert "equipe.txt" in [h.source for h in hits]


async def test_unrelated_question_scores_low_for_grounding(engine):
    tenant = await seed(engine)
    hits = await PgRetriever(engine, tenant, HashEmbedder(DIM)).search("recipe for chocolate cake")
    assert all(h.score < 0.35 for h in hits)


async def test_tenants_are_isolated(engine):
    t1 = await seed(engine)
    with DbSession(engine) as db:
        other = Tenant(name="other")
        db.add(other)
        db.commit()
        t2 = other.id
    assert await PgRetriever(engine, t2, HashEmbedder(DIM)).search("mobile apps") == []
    assert await PgRetriever(engine, t1, HashEmbedder(DIM)).search("mobile apps") != []


async def test_bm25_index_refreshes_after_reindex(engine):
    tenant = await seed(engine)
    retriever = PgRetriever(engine, tenant, HashEmbedder(DIM))
    assert not any("blockchain" in h.text.lower() for h in await retriever.search("blockchain consulting"))
    await index_document(engine, tenant, "new.txt", "We now offer blockchain consulting for supply chains.", HashEmbedder(DIM), DIM)
    assert any("blockchain" in h.text.lower() for h in await retriever.search("blockchain consulting"))


# --- concierge end to end ---------------------------------------------------------------------------
async def test_concierge_answers_from_indexed_documents_and_refuses_off_topic(engine):
    tenant = await seed(engine)
    retriever = PgRetriever(engine, tenant, HashEmbedder(DIM))
    llm = FakeLLM(["We build custom mobile apps and web platforms."])
    runners = build_runners(llm, retriever, None, default_registry(), retrieval_min_score=0.35)
    vault = PiiVault(crypto.FieldCipher(crypto.generate_key()), MemoryVaultStore())
    svc = ChatService(build_graph(runners, checkpointer=MemorySaver()), vault)

    answer = await svc.chat("s1", "What mobile apps do you build for logistics?")
    assert answer.reply.startswith("We build custom mobile apps") and "services.txt" in answer.reply
    refusal = await svc.chat("s2", "recipe for chocolate cake")
    assert "find a reliable answer" in refusal.reply and len(llm.calls) == 1
