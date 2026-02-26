"""
Shared embeddings module — single source of truth for MultiFallbackEmbeddings.

Used by both seed.py (ingestion) and rag_service.py (query-time).
"""
import logging
import time
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


class MultiFallbackEmbeddings:
    """HuggingFace Inference API embeddings with retry + model fallback.

    Produces 1024-dim vectors via BAAI/bge-m3 (primary) or
    BAAI/bge-large-en-v1.5 (fallback).  Both are 1024-dim so
    the Weaviate collection schema stays consistent.
    """

    PRIMARY_MODEL = "BAAI/bge-m3"                  # 1024 dims — best quality
    FALLBACK_MODELS = ["BAAI/bge-large-en-v1.5"]   # 1024 dims — fallback
    MAX_RETRIES = 3

    def __init__(self, api_key: str, model_name: str = ""):
        self.api_key = api_key
        self.model_name = model_name
        self.working_model: Optional[str] = None

    # ── low-level helpers ──────────────────────────────────────────────

    def _try_requests(self, text: str, model: str, timeout: int = 60):
        url = (
            f"https://router.huggingface.co/hf-inference/models/"
            f"{model}/pipeline/feature-extraction"
        )
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = requests.post(
            url, headers=headers, json={"inputs": text}, timeout=timeout
        )
        resp.raise_for_status()
        return resp.json()

    def _try_model(self, text: str, model: str):
        for attempt in range(self.MAX_RETRIES):
            try:
                result = self._try_requests(text, model)
                if result and len(result) > 0:
                    if self.working_model != model:
                        logger.info(f"Embedding model: {model} (1024-dim)")
                        self.working_model = model
                    return result
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Retry {attempt+1}/{self.MAX_RETRIES} for {model} "
                        f"in {wait}s: {e}"
                    )
                    time.sleep(wait)
                else:
                    logger.warning(
                        f"{model} failed after {self.MAX_RETRIES} retries"
                    )
        return None

    # ── public API ─────────────────────────────────────────────────────

    def embed_query(self, text: str):
        """Return a 1024-dim embedding vector for *text*."""
        # 1. Try cached working model
        if self.working_model:
            result = self._try_model(text, self.working_model)
            if result:
                return result
            self.working_model = None

        # 2. Try primary
        result = self._try_model(text, self.PRIMARY_MODEL)
        if result:
            return result

        # 3. Try fallbacks
        for model in self.FALLBACK_MODELS:
            result = self._try_model(text, model)
            if result:
                return result

        raise ValueError("All embedding models failed after retries")

    def embed_documents(self, texts: List[str]):
        """Embed a batch of texts sequentially."""
        return [self.embed_query(t) for t in texts]
