"""Per-agent views of the one shared knowledge index: include and exclude documents by name pattern.

One retriever serves every agent; a scope decides which documents an agent may be answered from (for example the
Solution Architect sees engineering material but not internal pricing notes). Patterns are shell-style and
case-insensitive, matched against the document's source name.

scopes.yaml:
    concierge:  {include: ["*"], exclude: ["Internal*"]}
    solution_architect: {include: ["Cloud*", "AI*", "Data*"]}
"""

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Dict, List, Protocol, Sequence

import yaml

from mpd_assistant.retrieval.hybrid import Hit


class Retriever(Protocol):
    async def search(self, query: str) -> List[Hit]: ...


class ScopedRetriever:
    def __init__(self, inner: Retriever, include: Sequence[str] = ("*",), exclude: Sequence[str] = ()):
        self._inner = inner
        self._include = [p.lower() for p in include] or ["*"]
        self._exclude = [p.lower() for p in exclude]

    def allows(self, source: str) -> bool:
        name = source.lower()
        return any(fnmatchcase(name, p) for p in self._include) and not any(fnmatchcase(name, p) for p in self._exclude)

    async def search(self, query: str) -> List[Hit]:
        return [h for h in await self._inner.search(query) if self.allows(h.source)]


def load_scopes(path: str | Path) -> Dict[str, Dict[str, List[str]]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    scopes: Dict[str, Dict[str, List[str]]] = {}
    for agent, rule in data.items():
        if not isinstance(rule, dict):
            raise ValueError(f"scope for {agent} must be a mapping with include/exclude lists")
        scopes[str(agent)] = {"include": [str(p) for p in rule.get("include", ["*"])], "exclude": [str(p) for p in rule.get("exclude", [])]}
    return scopes


def scoped_for(inner: Retriever, scopes: Dict[str, Dict[str, List[str]]], agent: str) -> Retriever:
    """The agent's view, or the full index when no scope is defined for it."""
    rule = scopes.get(agent)
    return ScopedRetriever(inner, rule["include"], rule["exclude"]) if rule else inner


__all__ = ["ScopedRetriever", "load_scopes", "scoped_for"]
