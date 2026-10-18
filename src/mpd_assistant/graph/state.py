from typing import Annotated, Any, Dict, List, Optional, TypedDict


def append_messages(left: List[Dict[str, Any]], right: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return (left or []) + (right or [])


class AgentState(TypedDict, total=False):
    """Graph state. Business values (prices, payment status) are never stored here, only ids."""

    messages: Annotated[List[Dict[str, Any]], append_messages]
    session_id: str
    user_id: Optional[str]
    verified: bool
    language: str
    intent: str
    agent: str
    mode: str
    requires_identity: bool
    response: Optional[str]
    steps: int
    escalated: bool
    reference: Optional[str]
