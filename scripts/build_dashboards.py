"""Generates Grafana dashboard JSON so panels stay consistent. Run: python scripts/build_dashboards.py"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "observability" / "grafana" / "dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}


def panel(pid, title, expr, x, y, unit="short", legend="{{agent}}"):
    return {
        "id": pid,
        "type": "timeseries",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": 12, "h": 8},
        "datasource": DS,
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "targets": [{"expr": expr, "legendFormat": legend, "refId": "A"}],
    }


def agent_health():
    hit = 'sum(rate(mpd_cache_events_total{result="hit"}[15m])) by (layer) / sum(rate(mpd_cache_events_total[15m])) by (layer)'
    panels = [
        panel(1, "Turns per minute by agent", "sum(rate(mpd_turns_total[5m])) by (agent) * 60", 0, 0),
        panel(2, "p95 latency by mode", "histogram_quantile(0.95, sum(rate(mpd_turn_latency_seconds_bucket[5m])) by (le, mode))", 12, 0, "s", "{{mode}}"),
        panel(3, "Mode mix", "sum(rate(mpd_turns_total[15m])) by (mode)", 0, 8, legend="{{mode}}"),
        panel(4, "Evaluator verdicts", "sum(rate(mpd_eval_verdicts_total[15m])) by (verdict)", 12, 8, legend="{{verdict}}"),
        panel(5, "Evaluator failure reasons", "sum(rate(mpd_eval_reasons_total[15m])) by (reason)", 0, 16, legend="{{reason}}"),
        panel(6, "Escalation rate", "sum(rate(mpd_escalations_total[1h])) / sum(rate(mpd_turns_total[1h]))", 12, 16, "percentunit", "escalation rate"),
        panel(7, "Tool calls by status", "sum(rate(mpd_tool_calls_total[5m])) by (tool, status)", 0, 24, legend="{{tool}} {{status}}"),
        panel(8, "Cache hit ratio", hit, 12, 24, "percentunit", "{{layer}}"),
        panel(9, "Tokens per minute", "sum(rate(mpd_tokens_total[5m])) by (agent, direction) * 60", 0, 32, legend="{{agent}} {{direction}}"),
        panel(10, "PII detections by boundary", "sum(rate(mpd_pii_detections_total[15m])) by (boundary, type)", 12, 32, legend="{{boundary}} {{type}}"),
    ]
    return {
        "uid": "mpd-agent-health",
        "title": "MPD Agent Health",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "tags": ["mpd"],
        "panels": panels,
    }


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "agent-health.json").write_text(json.dumps(agent_health(), indent=2), encoding="utf-8")
    print("wrote", OUT / "agent-health.json")
