"""Hybrid retriever on Postgres: pgvector similarity + BM25 keyword ranking, fused with RRF, optionally reranked.

Vector search runs in SQL (HNSW index). BM25 runs in an in-memory index per tenant that is rebuilt whenever the
corpus changes. On non-Postgres dialects (SQLite in unit tests) the vector side is computed in Python so the
fusion, scoring and tenant filtering are tested without a server.
"""

import asyncio
import math
from typing import Dict, List, Optional, Tuple

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.models import DocumentChunk
from mpd_assistant.retrieval.bm25 import TenantBm25Cache
from mpd_assistant.retrieval.embeddings import Embedder
from mpd_assistant.retrieval.hybrid import Hit, NoopReranker, Reranker, reciprocal_rank_fusion

Row = Tuple[str, str, str, float]  # id, source, text, cosine similarity

_VECTOR_SQL = text(
    "SELECT id, source, text, 1 - (embedding <=> CAST(:q AS vector)) AS sim FROM document_chunks "
    "WHERE tenant_id = :tenant ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
)
_SIM_FOR_IDS_SQL = text(
    "SELECT id, source, text, 1 - (embedding <=> CAST(:q AS vector)) AS sim FROM document_chunks "
    "WHERE tenant_id = :tenant AND id = ANY(:ids)"
)


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class PgRetriever:
    def __init__(
        self,
        engine: Engine,
        tenant_id: str,
        embedder: Embedder,
        reranker: Optional[Reranker] = None,
        candidates: int = 20,
        top_k: int = 5,
    ):
        self._engine, self._tenant = engine, tenant_id
        self._embedder = embedder
        self._reranker = reranker or NoopReranker()
        self._candidates, self._top_k = candidates, top_k
        self._bm25 = TenantBm25Cache()

    # --- corpus access ------------------------------------------------------------------------
    def _signature(self, db: DbSession) -> str:
        count, newest = db.execute(
            select(func.count(DocumentChunk.id), func.max(DocumentChunk.created_at)).where(DocumentChunk.tenant_id == self._tenant)
        ).one()
        return f"{count}:{newest}"

    def _bm25_ranking(self, query: str) -> List[Tuple[str, float]]:
        with DbSession(self._engine) as db:
            signature = self._signature(db)

            def load():
                rows = db.execute(select(DocumentChunk.id, DocumentChunk.text).where(DocumentChunk.tenant_id == self._tenant)).all()
                return [(r[0], r[1]) for r in rows]

            index = self._bm25.get(self._tenant, signature, load)
        return index.search(query, self._candidates)

    # --- rankings ------------------------------------------------------------------------------
    def _rankings(self, query: str, vector: List[float]) -> Tuple[List[Row], List[Row]]:
        bm25 = self._bm25_ranking(query)
        bm25_ids = [doc_id for doc_id, _ in bm25]

        if self._engine.dialect.name == "postgresql":
            literal = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
            params = {"q": literal, "tenant": self._tenant}
            with self._engine.connect() as conn:
                by_vector = [tuple(r) for r in conn.execute(_VECTOR_SQL, {**params, "k": self._candidates})]
                found = {r[0]: tuple(r) for r in conn.execute(_SIM_FOR_IDS_SQL, {**params, "ids": bm25_ids})} if bm25_ids else {}
        else:
            with DbSession(self._engine) as db:
                chunks = list(db.scalars(select(DocumentChunk).where(DocumentChunk.tenant_id == self._tenant)))
            scored = {c.id: (c.id, c.source, c.text, _cosine(vector, list(c.embedding))) for c in chunks}
            by_vector = sorted(scored.values(), key=lambda r: r[3], reverse=True)[: self._candidates]
            found = {i: scored[i] for i in bm25_ids if i in scored}

        by_text = [found[i] for i in bm25_ids if i in found]  # keeps BM25 order
        return by_vector, by_text

    async def search(self, query: str) -> List[Hit]:
        vector = (await self._embedder.embed([query]))[0]
        by_vector, by_text = await asyncio.to_thread(self._rankings, query, vector)

        similarity: Dict[str, float] = {r[0]: float(r[3]) for r in by_vector + by_text}
        as_hits = [[Hit(r[0], r[2], r[1], float(r[3])) for r in ranking] for ranking in (by_vector, by_text)]
        fused = reciprocal_rank_fusion(as_hits, top_n=self._candidates)
        # Fusion decides the order; the reported score is cosine similarity so grounding thresholds stay meaningful.
        ordered = [Hit(h.doc_id, h.text, h.source, similarity.get(h.doc_id, 0.0)) for h in fused]
        reranked = await self._reranker.rerank(query, ordered)
        return reranked[: self._top_k]
