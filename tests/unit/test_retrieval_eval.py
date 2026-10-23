from mpd_assistant.evaluation.offline.agentic import (
    RunRecord,
    check_thresholds,
    hallucination_rate,
    refusal_correctness,
    step_efficiency,
    summarize,
    tool_selection_accuracy,
)
from mpd_assistant.retrieval.hybrid import Hit, NoopReranker, cite, ground, reciprocal_rank_fusion


def H(i, score=0.0, source="a.docx"):
    return Hit(i, f"text {i}", source, score)


def test_rrf_rewards_agreement_between_rankers():
    bm25 = [H("a"), H("b"), H("c")]
    vector = [H("c"), H("a"), H("d")]
    fused = reciprocal_rank_fusion([bm25, vector])
    assert [h.doc_id for h in fused][:2] == ["a", "c"]
    assert {h.doc_id for h in fused} == {"a", "b", "c", "d"}


def test_rrf_is_deterministic_and_limits():
    ranks = [[H("x"), H("y")], [H("y"), H("x")]]
    assert [h.doc_id for h in reciprocal_rank_fusion(ranks)] == ["x", "y"]
    assert len(reciprocal_rank_fusion(ranks, top_n=1)) == 1


async def test_noop_reranker_and_grounding():
    hits = await NoopReranker().rerank("q", [H("a", 0.9), H("b", 0.1)])
    g = ground(hits)
    assert g.answerable and [h.doc_id for h in g.hits] == ["a"]
    assert not ground([H("z", 0.05)]).answerable
    assert not ground([]).answerable


def test_citations_are_unique_and_ordered():
    assert cite([H("1", source="a"), H("2", source="b"), H("3", source="a")]) == ["a", "b"]


def test_agentic_metrics():
    runs = [
        RunRecord("1", ["search"], ["search"], "faq", "faq", goal_met=True, steps=3),
        RunRecord("2", ["send_email"], [], "email_request", "faq", goal_met=False, steps=12),
        RunRecord("3", [], [], should_refuse=True, refused=True, goal_met=True, steps=1),
        RunRecord("4", [], [], answerable=False, answered=True, steps=1),
    ]
    assert tool_selection_accuracy(runs) == 0.5  # only runs 1 and 2 involve tools
    assert refusal_correctness(runs) == 1.0
    assert hallucination_rate(runs) == 1.0
    assert 0.9 < step_efficiency(runs) < 1.0
    summary = summarize(runs)
    failures = check_thresholds(summary)
    assert any(f.startswith("hallucination_rate") for f in failures)
    assert any(f.startswith("tool_selection_accuracy") for f in failures)


def test_thresholds_pass_when_all_good():
    good = [RunRecord("1", ["t"], ["t"], "faq", "faq", goal_met=True, steps=2)]
    assert check_thresholds(summarize(good)) == []
