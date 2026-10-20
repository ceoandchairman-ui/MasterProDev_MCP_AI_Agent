from typing import Annotated, Any, Dict, List, TypedDict


def append_messages(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return (left or []) + (right or [])


class AgentState(TypedDict, total=False):
    """Graph state. Business values (prices, payment status) are never stored here, only ids."""

    messages: Annotated[List[Dict[str, Any]], append_messages]
    session_id: str
    user_id: str | None
    verified: bool
    language: str
    intent: str
    agent: str
    mode: str
    requires_identity: bool
    response: str | None
    steps: int
    escalated: bool
    reference: str | None
    pending_action: Dict[str, Any] | None
    memory_context: str
    evidence: str | None
    thread_summary: str
    context_notes: str
    attachment_context: str
    style_examples: str
    session_row: str | None
    lead_slots: Dict[str, str]
    lead_stage: str
    scope: Dict[str, Any] | None
    quote_hash: str | None
    quote_id: str | None
    current_task: str | None
    task_queue: List[str]
    partials: List[str]
    eval_verdict: str | None
    eval_reasons: List[str]
