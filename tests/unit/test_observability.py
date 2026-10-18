import json
from pathlib import Path

from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from mpd_assistant.observability import metrics
from mpd_assistant.observability.otel import scrub_attributes

ROOT = Path(__file__).resolve().parents[2]


def test_metrics_record_and_expose():
    metrics.record_turn(agent="concierge", mode="templated", intent="greeting", seconds=0.2, verdict="pass", escalated=False)
    text = generate_latest(metrics.REGISTRY).decode()
    names = {f.name for f in text_string_to_metric_families(text)}
    assert {"mpd_turns", "mpd_turn_latency_seconds", "mpd_eval_verdicts"} <= names


def test_no_metric_has_high_cardinality_or_pii_label():
    forbidden = {"user", "user_id", "email", "phone", "session", "session_id", "message", "text", "query"}
    for metric in metrics.REGISTRY.collect():
        for sample in metric.samples:
            assert not forbidden & set(sample.labels), (metric.name, sample.labels)


def test_span_attributes_are_scrubbed():
    out = scrub_attributes({"q": "mail ann@example.com", "auth": "Bearer abcdefghijklmnopqrstuvwxyz", "n": 3})
    assert "ann@example.com" not in out["q"]
    assert "abcdefghijklmnopqrstuvwxyz" not in out["auth"]
    assert out["n"] == 3


def test_dashboard_json_is_valid_and_uses_existing_metrics():
    dash = json.loads((ROOT / "observability/grafana/dashboards/agent-health.json").read_text())
    exprs = " ".join(t["expr"] for p in dash["panels"] for t in p["targets"])
    for name in ("mpd_turns_total", "mpd_turn_latency_seconds_bucket", "mpd_eval_verdicts_total", "mpd_cache_events_total"):
        assert name in exprs
    assert len({p["id"] for p in dash["panels"]}) == len(dash["panels"])
