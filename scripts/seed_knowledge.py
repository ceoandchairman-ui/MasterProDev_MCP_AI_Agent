"""Index company documents into Postgres (pgvector). Idempotent: unchanged files are skipped.

Run as a one-off job:  python scripts/seed_knowledge.py
"""

import asyncio
from pathlib import Path

from mpd_assistant.core.config import get_settings
from mpd_assistant.core.db import ensure_tenant, make_engine
from mpd_assistant.ingestion.indexer import index_directory
from mpd_assistant.retrieval.embeddings import build_embedder


async def main() -> None:
    s = get_settings()
    embedder = build_embedder(s)
    if embedder is None:
        raise SystemExit("Set EMBEDDING_API_KEY or HUGGINGFACE_API_KEY")
    engine = make_engine(s.DATABASE_URL)
    results = await index_directory(engine, ensure_tenant(engine), Path(s.KNOWLEDGE_BASE_PATH), embedder)
    for name, status in results.items():
        print(f"{status:12} {name}")


if __name__ == "__main__":
    asyncio.run(main())
