"""Hosted reranker (Cohere-compatible /rerank API). Fails soft: on any error the original ranking is kept."""

from typing import List

import httpx

from mpd_assistant.retrieval.hybrid import Hit


class HostedReranker:
    def __init__(self, base_url: str, api_key: str, model: str, top_n: int = 5, client: httpx.AsyncClient | None = None, timeout: float = 8.0):
        self._url = base_url.rstrip("/") + "/rerank"
        self._key, self._model, self._top_n = api_key, model, top_n
        self._client, self._timeout = client, timeout

    async def rerank(self, query: str, hits: List[Hit]) -> List[Hit]:
        if len(hits) < 2:
            return hits
        payload = {"model": self._model, "query": query, "documents": [h.text for h in hits], "top_n": min(self._top_n, len(hits))}
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._client:
                resp = await self._client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            results = resp.json()["results"]
            return [Hit(hits[r["index"]].doc_id, hits[r["index"]].text, hits[r["index"]].source, float(r["relevance_score"])) for r in results]
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
            return hits
