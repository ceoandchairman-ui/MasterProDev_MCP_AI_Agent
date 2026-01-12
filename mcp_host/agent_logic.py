"""
This module contains the core agentic logic for handling multi-turn conversations,
especially for resuming tasks after interruptions like OAuth flows.
"""
import json
from typing import Dict, Any
from .state import state_manager
from .mcp_tools import execute_tool_by_name

async def handle_pending_action(session_id: str) -> Dict[str, Any]:
    """
    Checks for and executes a pending action stored in the conversation state.

    This is triggered after a user completes an external process like OAuth
    and confirms they are done. The agent can then resume its original task.
    """
    state = await state_manager.get_conversation_state(session_id)
    if not state or not state.pending_action:
        return {
            "status": "no_pending_action",
            "message": "I don't have a pending action to resume. What would you like to do next?"
        }

    pending_action = json.loads(state.pending_action)
    tool_name = pending_action.get("tool_name")
    params = pending_action.get("params")

    if not tool_name:
        return {"status": "error", "message": "Invalid pending action: missing tool name."}

    print(f"Resuming pending action for session {session_id}: {tool_name} with params {params}")

    # Clear the pending action from the state before executing
    state.pending_action = None
    await state_manager.update_conversation_state(session_id, state)

    # Re-execute the original tool call
    result = await execute_tool_by_name(tool_name, params)

    # Check if the action requires another auth flow (unlikely but possible)
    if isinstance(result, dict) and result.get("status") == "pending_auth":
        # The second attempt also failed, save it again.
        new_pending_action = {
            "tool_name": tool_name,
            "params": params
        }
        state.pending_action = json.dumps(new_pending_action)
        await state_manager.update_conversation_state(session_id, state)
        return {
            "status": "pending_auth",
            "message": "It seems I still don't have the right permissions. Please complete the authorization again.",
            "details": result.get("message")
        }

    return {
        "status": "resumed_action_completed",
        "tool_result": result,
        "message": f"Thanks for confirming! I've now completed the original request: {tool_name}."
    }
