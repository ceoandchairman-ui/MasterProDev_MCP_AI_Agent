from mpd_assistant.evaluation.online.rules import Verdict, evaluate_response
from mpd_assistant.graph.prar import build_prar


def make(planner=None, actor=None, reflector=None, **kw):
    async def default_planner(state):
        return [{"tool": "search", "query": state["goal"]}]

    async def default_actor(step, state):
        return {"step": step, "result": "found"}

    async def default_reflector(state):
        return {"done": True, "answer": "final", "note": "ok"}

    return build_prar(planner or default_planner, actor or default_actor, reflector or default_reflector, **kw)


async def test_prar_finishes_when_goal_met_and_records_timings():
    out = await make().ainvoke({"goal": "find x"})
    assert out["answer"] == "final" and out["stop_reason"] == "goal_met"
    assert set(out["timings"]) == {"plan", "act", "reflect"}
    assert len(out["observations"]) == 1


async def test_prar_replans_then_stops_at_loop_cap():
    plans = []

    async def planner(state):
        plans.append(state.get("loops", 0))
        return [{"n": len(plans)}]

    async def never_done(state):
        return {"done": False, "note": "not yet"}

    out = await make(planner=planner, reflector=never_done, max_loops=3).ainvoke({"goal": "g"})
    assert out["stop_reason"] == "max_loops" and out["loops"] == 3 and plans == [0, 1, 2]


async def test_prar_caps_total_actions():
    async def planner(state):
        return [{"i": i} for i in range(10)]

    async def never_done(state):
        return {"done": False}

    out = await make(planner=planner, reflector=never_done, max_actions=4, max_loops=5).ainvoke({"goal": "g"})
    assert out["actions_taken"] == 4 and out["stop_reason"] == "max_actions"


def test_eval_passes_clean_response():
    assert evaluate_response("We build custom software for clients.").verdict is Verdict.PASS


def test_eval_flags_problems():
    assert evaluate_response("").reasons == ["empty_response"]
    assert evaluate_response("Sure: TOOL: send_email").reasons == ["tool_syntax_leak"]
    assert "unresolved_pii_token" in evaluate_response("I emailed <EMAIL_1>").reasons
    assert "prompt_or_boilerplate_leak" in evaluate_response("As an AI language model I cannot").reasons
    assert "too_long" in evaluate_response("a" * 5000).reasons


def test_eval_pii_leak_escalates():
    result = evaluate_response("Their number is (416) 967-1111")
    assert result.verdict is Verdict.ESCALATE and result.reasons == ["pii_leak"]


def test_eval_language_mismatch():
    assert "wrong_language" in evaluate_response("Hello, thanks for the question and the time you gave us", language="fr").reasons
    assert evaluate_response("Bonjour, merci pour votre message et votre temps", language="fr").verdict is Verdict.PASS
