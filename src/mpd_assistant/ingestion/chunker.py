"""Paragraph-aware chunking with overlap, so answers keep their surrounding context."""

import re
from typing import List

TARGET_CHARS = 900
OVERLAP_CHARS = 150
MIN_CHARS = 40


def _split_long(paragraph: str, limit: int) -> List[str]:
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    parts, current = [], ""
    for sentence in sentences:
        while len(sentence) > limit:  # no sentence boundary: hard split
            parts.append(sentence[:limit])
            sentence = sentence[limit:]
        if current and len(current) + len(sentence) + 1 > limit:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def chunk_text(text: str, target: int = TARGET_CHARS, overlap: int = OVERLAP_CHARS) -> List[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]
    pieces: List[str] = []
    for p in paragraphs:
        pieces.extend(_split_long(p, target) if len(p) > target else [p])

    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > target:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = (tail + "\n\n" + piece).strip() if tail else piece
        else:
            current = f"{current}\n\n{piece}".strip() if current else piece
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= MIN_CHARS] or ([text.strip()] if len(text.strip()) >= 1 else [])
