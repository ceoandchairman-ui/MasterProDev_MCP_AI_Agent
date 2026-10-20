"""Concierge: answers questions from company knowledge, with citations, or says it has no reliable answer."""

from typing import Any, Dict, List, Protocol

from mpd_assistant.agents.common import memory_note
from mpd_assistant.agents.context import HISTORY_BUDGET, NOTE_BUDGET, needs_rewrite, recent_turns, transcript
from mpd_assistant.agents.prompts import load_prompt
from mpd_assistant.core.llm.client import LLM, LLMError
from mpd_assistant.graph.state import AgentState
from mpd_assistant.responses.engine import render
from mpd_assistant.retrieval.hybrid import Hit, cite, ground

SYSTEM = load_prompt("concierge", "system")
REWRITE = load_prompt("concierge", "rewrite")
MAX_QUERY_CHARS = 300
PROMPT_VERSION = SYSTEM.version


class Retriever(Protocol):
    async def search(self, query: str) -> List[Hit]: ...


def _last_user(state: AgentState) -> str:
    return next((m["content"] for m in reversed(state.get("messages", [])) if m.get("role") == "user"), "")


async def standalone_question(llm: LLM, history, question: str) -> str:
    """The latest message restated so it can be searched without the conversation. Any problem returns the message as it
    was, because a plain search is better than no search."""
    try:
        result = await llm.complete(
            [{"role": "system", "content": REWRITE.render()}, {"role": "user", "content": f"Conversation so far:\n{transcript(history)}\n\nLatest message: {question}"}],
            tier="cheap",
            max_tokens=80,
            temperature=0.0,
        )
    except LLMError:
        return question
    lines = (result.text or "").strip().splitlines()
    rewritten = lines[0].strip().strip("\"'").strip() if lines else ""
    return rewritten if 0 < len(rewritten) <= MAX_QUERY_CHARS and "{" not in rewritten else question


def make_concierge(llm: LLM, retriever: Retriever, min_score: float = 0.2):
    async def run(state: AgentState) -> Dict[str, Any]:
        language = state.get("language", "en")
        question = _last_user(state)
        history = recent_turns(state, HISTORY_BUDGET["concierge"])
        query = await standalone_question(llm, history, question) if needs_rewrite(question, bool(history)) else question
        grounding = ground(await retriever.search(query), min_score=min_score)
        if not grounding.answerable:
            return {"response": render("no_answer", language)}

        context = "\n\n".join(f"[{i + 1}] {h.text}" for i, h in enumerate(grounding.hits[:4]))
        try:
            result = await llm.complete(
                [
                    {"role": "system", "content": SYSTEM.render(language=language)},
                    *history,
                    {"role": "user", "content": f"{memory_note(state, NOTE_BUDGET['concierge'])}Context:\n{context}\n\nQuestion: {question}"},
                ],
                tier="mid",  # customer-facing answers get the stronger model; volume is modest
                max_tokens=400,
            )
        except LLMError:
            return {"response": render("temporary_error", language)}
        sources = cite(grounding.hits[:4])
        footer = f"\n\nSources: {', '.join(sources)}" if sources else ""
        return {"response": result.text.strip() + footer, "evidence": context}

    return run
