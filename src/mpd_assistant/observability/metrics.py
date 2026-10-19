"""Prometheus metrics. Labels are low-cardinality enums only: never user text, ids or personal data."""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

TURNS = Counter("mpd_turns_total", "Conversation turns", ["agent", "mode", "intent"], registry=REGISTRY)
TURN_LATENCY = Histogram(
    "mpd_turn_latency_seconds",
    "End-to-end turn latency",
    ["mode"],
    buckets=(0.1, 0.3, 1, 2, 5, 10, 15, 30, 60),
    registry=REGISTRY,
)
TOKENS = Counter("mpd_tokens_total", "LLM tokens", ["agent", "direction"], registry=REGISTRY)
TOOL_CALLS = Counter("mpd_tool_calls_total", "Tool calls", ["tool", "status"], registry=REGISTRY)
TOOL_LATENCY = Histogram("mpd_tool_latency_seconds", "Tool latency", ["tool"], registry=REGISTRY)
CACHE_EVENTS = Counter("mpd_cache_events_total", "Cache lookups", ["layer", "result"], registry=REGISTRY)
EVAL_VERDICTS = Counter("mpd_eval_verdicts_total", "Online evaluator verdicts", ["verdict"], registry=REGISTRY)
EVAL_REASONS = Counter("mpd_eval_reasons_total", "Evaluator failure reasons", ["reason"], registry=REGISTRY)
ESCALATIONS = Counter("mpd_escalations_total", "Escalations to a human", ["reason"], registry=REGISTRY)
PII_DETECTIONS = Counter("mpd_pii_detections_total", "PII detected at a boundary", ["boundary", "type"], registry=REGISTRY)
MESSAGES = Counter("mpd_messages_total", "Outbound messages", ["channel", "purpose", "status"], registry=REGISTRY)
JUDGE_VERDICTS = Counter("mpd_judge_verdicts_total", "LLM judge outcomes", ["verdict"], registry=REGISTRY)
BUDGET_BLOCKS = Counter("mpd_budget_blocks_total", "Requests stopped by a token budget", ["scope"], registry=REGISTRY)
EVAL_SCORE = Gauge("mpd_eval_score", "Latest offline evaluation score", ["suite", "metric"], registry=REGISTRY)
PROMPT_PREFIX = Counter("mpd_prompt_prefix_total", "Whether a call's system prompt matched a recent one (stable prefixes get provider prompt-cache hits)", ["agent", "result"], registry=REGISTRY)
DEGRADED = Counter("mpd_degraded_total", "Turns served in a degraded way because a dependency failed", ["dependency"], registry=REGISTRY)
INGEST_DOCUMENTS =Counter("mpd_ingest_documents_total", "Knowledge documents processed by the indexer", ["result"], registry=REGISTRY)
UPLOADS = Counter("mpd_uploads_total", "User file uploads", ["kind", "result"], registry=REGISTRY)
PAYMENTS = Counter("mpd_payments_total", "Payment events", ["event"], registry=REGISTRY)
PRAR_PHASE =Histogram("mpd_prar_phase_seconds", "Plan/act/reflect phase time", ["agent", "phase"], registry=REGISTRY)


def record_turn(*, agent: str, mode: str, intent: str, seconds: float, verdict: str | None, escalated: bool, reasons=()):
    TURNS.labels(agent, mode, intent).inc()
    TURN_LATENCY.labels(mode).observe(seconds)
    if verdict:
        EVAL_VERDICTS.labels(verdict).inc()
    for reason in reasons:
        EVAL_REASONS.labels(reason).inc()
    if escalated:
        ESCALATIONS.labels(reason=intent).inc()
