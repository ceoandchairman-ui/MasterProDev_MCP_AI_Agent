"""Embedding clients. The endpoint and model are configuration, so any OpenAI-compatible server works."""

import hashlib
import math
import re
from typing import List, Optional, Protocol

import httpx

BATCH = 32


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    async def embed(self, texts: List[str]) -> List[List[float]]: ...


class OpenAICompatibleEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, client: Optional[httpx.AsyncClient] = None, timeout: float = 30.0):
        self._url = base_url.rstrip("/") + "/embeddings"
        self._key, self._model, self._client, self._timeout = api_key, model, client, timeout

    async def _post(self, batch: List[str]) -> List[List[float]]:
        payload = {"model": self._model, "input": batch}
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._client:
                resp = await self._client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise EmbeddingError(f"Embedding call failed: {type(exc).__name__}") from exc  # never include key or body

    async def embed(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), BATCH):
            out.extend(await self._post(texts[i : i + BATCH]))
        if len(out) != len(texts):
            raise EmbeddingError("Embedding count mismatch")
        return out


class HashEmbedder:
    """Deterministic bag-of-words embedder for tests: similar wording gives similar vectors."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    async def embed(self, texts: List[str]) -> List[List[float]]:
        vectors = []
        for text in texts:
            v = [0.0] * self.dim
            for word in re.findall(r"\w+", text.lower()):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            vectors.append([x / norm for x in v])
        return vectors
