"""Concierge: answers questions from company knowledge, with citations, or says it has no reliable answer."""

from typing import Any, Dict, List, Protocol

from mpd_assistant.agents.common import memory_note
from mpd_assistant.agents.prompts import load_prompt
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.graph.state import AgentState
from mpd_assistant.responses.engine import render
from mpd_assistant.retrieval.hybrid import Hit, cite, ground

SYSTEM = load_prompt("concierge", "system")
PROMPT_VERSION = SYSTEM.version


class Retriever(Protocol):
    async def search(self, query: str) -> List[Hit]: ...


def _last_user(state: AgentState) -> str:
    return next((m["content"] for m in reversed(state.get("messages", [])) if m.get("role") == "user"), "")


def make_concierge(llm: LLM, retriever: Retriever, min_score: float = 0.2):
    async def run(state: AgentState) -> Dict[str, Any]:
        language = state.get("language", "en")
        question = _last_user(state)
        grounding = ground(await retriever.search(question), min_score=min_score)
        if not grounding.answerable:
            return {"response": render("no_answer", language)}

        context = "\n\n".join(f"[{i + 1}] {h.text}" for i, h in enumerate(grounding.hits[:4]))
        try:
            result = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM.render(language=language)},
                    {"role": "user", "content": f"{memory_note(state)}Context:\n{context}\n\nQuestion: {question}"},
                ],
                tier="cheap",
                max_tokens=400,
            )
        except LLMError:
            return {"response": render("temporary_error", language)}
        sources = cite(grounding.hits[:4])
        footer = f"\n\nSources: {', '.join(sources)}" if sources else ""
        return {"response": result.text.strip() + footer, "evidence": context}

    return run
