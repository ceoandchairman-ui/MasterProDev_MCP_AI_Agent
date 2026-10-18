"""Strangler switch: a deterministic share of conversations is answered by the new pipeline.

Default is 0%, so production behavior does not change until the percentage is raised deliberately.
"""

import logging
from functools import lru_cache
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _new_chat():
    from mpd_assistant.api.app import build_services

    return build_services().chat


def routes_to_new(session_key: str, percent: int) -> bool:
    if percent <= 0 or not session_key:
        return False
    from mpd_assistant.core.flags import enabled_for  # imported here so the legacy host starts without the new package

    return enabled_for(session_key, percent)


async def answer(session_key: str, message: str, verified: bool, user_id: Optional[str]) -> Dict[str, Any]:
    result = await _new_chat().chat(session_key, message, verified=verified, user_id=user_id)
    return {"response": result.reply, "tool_calls": [], "execution_time": 0.0, "pipeline": "new"}
