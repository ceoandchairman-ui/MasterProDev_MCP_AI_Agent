"""Wires agents to their dependencies. Agents without a dependency are simply not registered (templates answer)."""

from typing import Dict

from mpd_assistant.agents.comms_scheduling.agent import make_comms
from mpd_assistant.agents.concierge.agent import Retriever, make_concierge
from mpd_assistant.agents.lead_conversion.agent import LeadRepository, make_lead_conversion
from mpd_assistant.agents.payment.agent import make_payment_node
from mpd_assistant.agents.quote.agent import make_quote_agent
from mpd_assistant.agents.solution_architect.agent import make_solution_architect
from mpd_assistant.business.quoting import CatalogItem
from mpd_assistant.core.llm.client import LLM
from mpd_assistant.core.llm.metered import MeteredLLM
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
    on_booked=None,
    retrieval_min_score: float = 0.2,
    google_token_provider=None,
    on_quote_review=None,
    budget=None,
    quotes=None,
    payments=None,
    has_step_up=None,
    start_step_up=None,
    companies=None,
) -> Dict[Agent, object]:
    runners: Dict[Agent, object] = {}
    if payments is not None:
        runners[Agent.PAYMENT] = make_payment_node(payments, has_step_up, start_step_up)  # code, works without a model
    if llm is None:
        return runners
    if retriever is not None:
        runners[Agent.CONCIERGE] = make_concierge(MeteredLLM(llm, "concierge", budget), retriever, retrieval_min_score)
    if executor is not None:
        runners[Agent.COMMS_SCHEDULING] = make_comms(MeteredLLM(llm, "comms_scheduling", budget), executor, registry, on_booked, google_token_provider)
    if leads is not None:
        runners[Agent.LEAD_CONVERSION] = make_lead_conversion(MeteredLLM(llm, "lead_conversion", budget), leads, companies)
    runners[Agent.SOLUTION_ARCHITECT] = make_solution_architect(MeteredLLM(llm, "solution_architect", budget))
    if catalog:
        def save_quote(state, quote):
            return quotes.save(state["user_id"], quote) if quotes is not None and state.get("user_id") else None

        runners[Agent.QUOTE] = make_quote_agent(MeteredLLM(llm, "quote", budget), catalog, on_quote=save_quote, on_review=on_quote_review)
    return runners
