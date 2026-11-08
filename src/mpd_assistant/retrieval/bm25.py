"""BM25 keyword ranking (rank_bm25.BM25Plus; its IDF stays positive on small corpora) with accent-folding, multilingual-friendly tokenization."""

import re
import unicodedata
from typing import Dict, List, Sequence, Tuple

from rank_bm25 import BM25Plus

_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it of on or that the to was were will with "
    "au aux ce ces dans de des du elle en et il je la le les leur nous on ou par pour que qui se son sur un une vous est sont".split()
)


def fold(text: str) -> str:
    """Lowercase and strip accents so 'équipe' matches 'equipe'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"\w+", fold(text)) if len(t) > 1 and t not in _STOPWORDS]


class Bm25Index:
    """In-memory index over (id, text) pairs. Cheap to build for knowledge bases of this size."""

    def __init__(self, documents: Sequence[Tuple[str, str]]):
        self._ids: List[str] = [d[0] for d in documents]
        corpus = [tokenize(d[1]) for d in documents]
        self._vocab = [set(tokens) for tokens in corpus]
        self._bm25 = BM25Plus(corpus) if any(corpus) else None

    def __len__(self) -> int:
        return len(self._ids)

    def search(self, query: str, k: int = 20) -> List[Tuple[str, float]]:
        tokens = tokenize(query)
        if not tokens or self._bm25 is None:
            return []
        wanted = set(tokens)
        scores = self._bm25.get_scores(tokens)
        # BM25Plus gives every document a small bonus per known query term; keep only real term matches.
        pairs = zip(self._ids, scores, self._vocab, strict=True)
        matched = [(doc_id, float(score)) for doc_id, score, vocab in pairs if wanted & vocab]
        return sorted(matched, key=lambda p: p[1], reverse=True)[:k]


class TenantBm25Cache:
    """One index per tenant, rebuilt when the corpus signature (chunk count + latest hash) changes."""

    def __init__(self):
        self._indexes: Dict[str, Tuple[str, Bm25Index]] = {}

    def get(self, tenant_id: str, signature: str, loader) -> Bm25Index:
        cached = self._indexes.get(tenant_id)
        if cached and cached[0] == signature:
            return cached[1]
        index = Bm25Index(loader())
        self._indexes[tenant_id] = (signature, index)
        return index
