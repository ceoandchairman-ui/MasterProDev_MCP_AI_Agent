"""Plan -> Act -> Reflect loop as a reusable LangGraph subgraph with hard bounds and per-phase timing.

The planner, actor and reflector are injected, so each agent supplies its own prompts and tools
and tests run without an LLM. 'Reason' is the planner's chain of thought; the graph keeps only its output.
"""

import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

MAX_LOOPS = 3
MAX_ACTIONS = 8


class PrarState(TypedDict, total=False):
    goal: str
    context: Dict[str, Any]
    plan: List[Dict[str, Any]]
    observations: List[Dict[str, Any]]
    answer: Optional[str]
    done: bool
    loops: int
    actions_taken: int
    reflection: str
    timings: Dict[str, float]
    stop_reason: Optional[str]


Planner = Callable[[PrarState], Awaitable[List[Dict[str, Any]]]]
Actor = Callable[[Dict[str, Any], PrarState], Awaitable[Dict[str, Any]]]
Reflector = Callable[[PrarState], Awaitable[Dict[str, Any]]]  # -> {"done": bool, "answer": str|None, "note": str}


def _timed(state: PrarState, phase: str, started: float) -> Dict[str, float]:
    timings = dict(state.get("timings", {}))
    timings[phase] = timings.get(phase, 0.0) + (time.perf_counter() - started)
    return timings


def build_prar(planner: Planner, actor: Actor, reflector: Reflector, max_loops: int = MAX_LOOPS, max_actions: int = MAX_ACTIONS):
    async def plan_node(state: PrarState) -> Dict[str, Any]:
        t = time.perf_counter()
        plan = await planner(state)
        return {"plan": plan, "timings": _timed(state, "plan", t)}

    async def act_node(state: PrarState) -> Dict[str, Any]:
        t = time.perf_counter()
        observations = list(state.get("observations", []))
        taken = state.get("actions_taken", 0)
        for step in state.get("plan", []):
            if taken >= max_actions:
                break
            observations.append(await actor(step, state))
            taken += 1
        return {"observations": observations, "actions_taken": taken, "timings": _timed(state, "act", t)}

    async def reflect_node(state: PrarState) -> Dict[str, Any]:
        t = time.perf_counter()
        verdict = await reflector(state)
        loops = state.get("loops", 0) + 1
        update: Dict[str, Any] = {
            "loops": loops,
            "reflection": verdict.get("note", ""),
            "timings": _timed(state, "reflect", t),
        }
        if verdict.get("done"):
            update.update(done=True, answer=verdict.get("answer"), stop_reason="goal_met")
        elif loops >= max_loops:
            update.update(done=True, stop_reason="max_loops")
        elif state.get("actions_taken", 0) >= max_actions:
            update.update(done=True, stop_reason="max_actions")
        return update

    def route_after_reflect(state: PrarState) -> str:
        return END if state.get("done") else "plan"

    graph = StateGraph(PrarState)
    graph.add_node("plan", plan_node)
    graph.add_node("act", act_node)
    graph.add_node("reflect", reflect_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "act")
    graph.add_edge("act", "reflect")
    graph.add_conditional_edges("reflect", route_after_reflect, {END: END, "plan": "plan"})
    return graph.compile()
