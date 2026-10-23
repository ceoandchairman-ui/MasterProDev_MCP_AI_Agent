"""Untrusted content (email bodies, uploaded files, retrieved web text): delimited, and never a trigger by itself."""

import re

_CLOSE = re.compile(r"</?\s*untrusted[^>]*>", re.IGNORECASE)
_INSTRUCTION = re.compile(r"(?i)\b(ignore (all |any |the )?(previous|above|prior) instructions|system prompt|you are now|send (this|the following) to)\b")


def wrap(text: str, source: str) -> str:
    """Escape any tag that would close the block early, then delimit the content as data."""
    safe_source = re.sub(r"[^A-Za-z0-9_.:-]", "_", source)[:60]
    body = _CLOSE.sub("[tag removed]", text or "")
    return f'<untrusted source="{safe_source}">\n{body}\n</untrusted>'


def looks_like_injection(text: str) -> bool:
    return bool(_INSTRUCTION.search(text or ""))
