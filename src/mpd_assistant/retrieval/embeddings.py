"""Embedding clients. The endpoint and model are configuration: any OpenAI-compatible server works, and so does
HuggingFace's own feature-extraction endpoint (the one the legacy host used)."""

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Callable
from typing import List, Protocol

import httpx

from mpd_assistant.retrieval.bm25 import tokenize

BATCH = 32
HF_INFERENCE_BASE = "https://router.huggingface.co/hf-inference"


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    async def embed(self, texts: List[str]) -> List[List[float]]: ...


class OpenAICompatibleEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str, client: httpx.AsyncClient | None = None, timeout: float = 30.0):
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


class HuggingFaceEmbedder:
    """HuggingFace hf-inference feature-extraction: POST <base>/models/<model>/pipeline/feature-extraction with
    {"inputs": [...]}, answered by one vector per input. A busy or cold model (429, 503) is retried briefly."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = HF_INFERENCE_BASE,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        retry_delays: tuple = (1.0, 3.0),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._url = f"{base_url.rstrip('/')}/models/{model}/pipeline/feature-extraction"
        self._key, self._client, self._timeout = api_key, client, timeout
        self._delays, self._sleep = retry_delays, sleep

    async def _send(self, batch: List[str]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._key}"}
        if self._client:
            return await self._client.post(self._url, json={"inputs": batch}, headers=headers, timeout=self._timeout)
        async with httpx.AsyncClient() as client:
            return await client.post(self._url, json={"inputs": batch}, headers=headers, timeout=self._timeout)

    async def _post(self, batch: List[str]) -> List[List[float]]:
        try:
            resp = await self._send(batch)
            for delay in self._delays:
                if resp.status_code not in (429, 503):
                    break
                await self._sleep(delay)
                resp = await self._send(batch)
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Embedding call failed: {type(exc).__name__}") from exc  # never include key or body
        if resp.status_code != 200:
            raise EmbeddingError(f"Embedding call failed: HTTP {resp.status_code}")  # the status helps diagnose; the body is not shown
        try:
            vectors = resp.json()
        except ValueError as exc:
            raise EmbeddingError("Embedding call failed: invalid JSON") from exc
        ok = (
            isinstance(vectors, list)
            and len(vectors) == len(batch)
            and all(isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v) for v in vectors)
        )
        if not ok:  # for example token-level output, or a different count than we sent
            raise EmbeddingError("Embedding call failed: unexpected response shape")
        return vectors

    async def embed(self, texts: List[str]) -> List[List[float]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), BATCH):
            out.extend(await self._post(texts[i : i + BATCH]))
        if len(out) != len(texts):
            raise EmbeddingError("Embedding count mismatch")
        return out


def build_embedder(settings) -> "Embedder | None":
    """The embedder the settings describe, or None when there is no key. EMBEDDING_FORMAT is auto, openai or huggingface;
    auto picks huggingface when there is no EMBEDDING_BASE_URL or it points at hf-inference, and openai otherwise."""
    key = settings.EMBEDDING_API_KEY or settings.HUGGINGFACE_API_KEY
    if not key:
        return None
    base = settings.EMBEDDING_BASE_URL
    fmt = (settings.EMBEDDING_FORMAT or "auto").lower()
    if fmt == "auto":
        fmt = "huggingface" if (not base or "hf-inference" in base) else "openai"
    if fmt == "huggingface":
        return HuggingFaceEmbedder(key, settings.EMBEDDING_MODEL, base or HF_INFERENCE_BASE)
    return OpenAICompatibleEmbedder(base or settings.LLM_BASE_URL, key, settings.EMBEDDING_MODEL)


class HashEmbedder:
    """Deterministic bag-of-words embedder for tests: similar wording gives similar vectors."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    async def embed(self, texts: List[str]) -> List[List[float]]:
        vectors = []
        for text in texts:
            v = [0.0] * self.dim
            for word in tokenize(text):
                v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            vectors.append([x / norm for x in v])
        return vectors
