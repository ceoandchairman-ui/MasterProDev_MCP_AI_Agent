"""Wires agents to their dependencies. Agents without a dependency are simply not registered (templates answer)."""

from typing import Dict

from mpd_assistant.agents.comms_scheduling.agent import make_comms
from mpd_assistant.agents.concierge.agent import Retriever, make_concierge
from mpd_assistant.agents.lead_conversion.agent import LeadRepository, make_lead_conversion
from mpd_assistant.agents.quote.agent import make_quote_agent
from mpd_assistant.agents.solution_architect.agent import make_solution_architect
from mpd_assistant.business.quoting import CatalogItem
from mpd_assistant.core.llm.client import LLM
from mpd_assistant.routing.intents import Agent
from mpd_assistant.tools.executor import ToolExecutor
from mpd_assistant.tools.registry import ToolRegistry


def build_runners(
    llm: LLM | None,
    retriever: Retriever | None,
    executor: ToolExecutor | None,
    registry: ToolRegistry,
    leads: LeadRepository | None = None,
    catalog: Dict[str, CatalogItem] | None = None,
) -> Dict[Agent, object]:
    runners: Dict[Agent, object] = {}
    if llm is None:
        return runners
    if retriever is not None:
        runners[Agent.CONCIERGE] = make_concierge(llm, retriever)
    if executor is not None:
        runners[Agent.COMMS_SCHEDULING] = make_comms(llm, executor, registry)
    if leads is not None:
        runners[Agent.LEAD_CONVERSION] = make_lead_conversion(llm, leads)
    runners[Agent.SOLUTION_ARCHITECT] = make_solution_architect(llm)
    if catalog:
        runners[Agent.QUOTE] = make_quote_agent(llm, catalog)
    return runners
