"""Idempotent knowledge indexing into document_chunks. Re-running only re-embeds documents that changed."""

import asyncio
import hashlib
from pathlib import Path
from typing import Dict

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session as DbSession

from mpd_assistant.core.models import EMBEDDING_DIM, DocumentChunk
from mpd_assistant.ingestion.chunker import chunk_text
from mpd_assistant.retrieval.embeddings import Embedder

TEXT_SUFFIXES = {".txt", ".md"}


class IndexError_(RuntimeError):
    pass


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        from docx import Document

        doc = Document(str(path))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            parts.extend(" | ".join(cell.text.strip() for cell in row.cells) for row in table.rows)
        return "\n\n".join(p for p in parts if p.strip())
    raise IndexError_(f"Unsupported file type: {suffix}")


async def index_document(engine: Engine, tenant_id: str, source: str, text: str, embedder: Embedder, expected_dim: int = EMBEDDING_DIM) -> str:
    """Returns 'indexed', 'unchanged' or 'empty'."""
    doc_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with DbSession(engine) as db:
        existing = db.scalar(
            select(DocumentChunk.doc_hash).where(DocumentChunk.tenant_id == tenant_id, DocumentChunk.source == source).limit(1)
        )
    if existing == doc_hash:
        return "unchanged"

    chunks = chunk_text(text)
    if not chunks:
        return "empty"
    vectors = await embedder.embed(chunks)
    if any(len(v) != expected_dim for v in vectors):
        raise IndexError_(f"Embedding dimension mismatch (expected {expected_dim})")

    with DbSession(engine) as db:
        db.execute(delete(DocumentChunk).where(DocumentChunk.tenant_id == tenant_id, DocumentChunk.source == source))
        for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            db.add(DocumentChunk(tenant_id=tenant_id, source=source, doc_hash=doc_hash, chunk_index=i, text=chunk, embedding=vector))
        db.commit()
    return "indexed"


async def index_directory(engine: Engine, tenant_id: str, directory: Path, embedder: Embedder, expected_dim: int = EMBEDDING_DIM) -> Dict[str, str]:
    results: Dict[str, str] = {}
    for path in sorted(directory.iterdir()):
        if path.name.startswith("~$") or path.suffix.lower() not in TEXT_SUFFIXES | {".docx"}:
            continue
        try:
            text = await asyncio.to_thread(read_document, path)
            results[path.name] = await index_document(engine, tenant_id, path.name, text, embedder, expected_dim)
        except Exception as exc:
            results[path.name] = f"failed:{type(exc).__name__}"
    return results
