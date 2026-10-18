"""Wires agents to their dependencies. Agents without a dependency are simply not registered (templates answer)."""

from typing import Dict

from mpd_assistant.agents.comms_scheduling.agent import make_comms
from mpd_assistant.agents.concierge.agent import Retriever, make_concierge
from mpd_assistant.core.llm.client import LLM
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.executor import ToolExecutor
from mpd_assistant.tools.registry import ToolRegistry


def build_runners(llm: LLM | None, retriever: Retriever | None, executor: ToolExecutor | None, registry: ToolRegistry) -> Dict[Agent, object]:
    runners: Dict[Agent, object] = {}
    if llm is None:
        return runners
    if retriever is not None:
        runners[Agent.CONCIERGE] = make_concierge(llm, retriever)
    if executor is not None:
        runners[Agent.COMMS_SCHEDULING] = make_comms(llm, executor, registry)
    return runners
