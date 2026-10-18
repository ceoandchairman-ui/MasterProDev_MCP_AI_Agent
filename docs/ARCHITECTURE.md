# Architecture and status

## Request flow (new pipeline, `src/mpd_assistant`)

```
client -> POST /v2/chat
  ChatService.chat
    PiiVault.tokenize        raw PII -> <EMAIL_1> tokens (encrypted vault, per session)
    graph (LangGraph)
      supervisor             rule router: intent, language, agent, mode, identity requirement
      identity_gate | template | agent_<name> | escalate
      evaluate               deterministic checks: PII leak, tool-syntax leak, language, length
      persist                tokenized reply appended to the checkpointed thread
    PiiVault.detokenize      values restored only for the same session
    final evaluation         values never issued to this session escalate instead of being sent
```

Rules enforced in code, not prompts: default-deny tool registry, role checks, identity gate for
quote/scope/booking/email intents, bounded plan-act-reflect loops, supersede-not-overwrite memory,
quotes priced by code and verified against a content hash before payment.

## Module map

| Package | Purpose |
|---|---|
| `core` | settings, scrubbing logging, field encryption + blind index, SQL models |
| `privacy` | PII detector (Luhn cards/SIN, email, phone, postal, secrets), reversible vault |
| `identity` | normalization (E.164), OTP service, sign-up/verify service, senders |
| `routing`, `responses` | intent taxonomy, router, mode ladder; YAML templates (en, fr) |
| `graph` | state, builder, PRAR subgraph, `ChatService` boundary |
| `memory` | token-budget window, context assembler, long-term store |
| `sessions`, `cache`, `business`, `tools` | lifecycle, response cache, funnel/quoting/escalation, tool registry |
| `agents` | Concierge, Lead Conversion, Solution Architect, Quote, Comms & Scheduling + factory |
| `retrieval`, `evaluation` | RRF fusion + grounding; online rules + offline agentic metrics |
| `observability` | Prometheus metrics, OTel setup with scrubbing |
| `api` | v2 FastAPI app and the `create()` ASGI factory |

Legacy code (`mcp_host/`, `mcp_servers/`) still runs the current product and has been hardened
(service-key auth, role policy, escaped output, rate limits). It is removed after the new pipeline
reaches parity.

## Built and tested (183 unit tests)

Everything in the module map, plus: LLM client (OpenAI-compatible, fallback), guarded tool executor
(permissions, confirmation, privacy-token rehydration at the tool boundary), five agents
(Concierge, Lead Conversion, Solution Architect, Quote, Comms & Scheduling) with Escalation handled
by the graph, the Alembic baseline, Grafana/Prometheus/OTel configs, CI workflow, `api.Dockerfile`
and Railway config. All agents are tested with a fake LLM; none has run against a live model.

## Not built yet (known gaps)

- Sessions, PII vault, user records and leads are **process memory** in the new API. Until
  Postgres/Redis repositories replace them, run **one replica** (set in `deploy/railway/api.toml`)
  and do not route production traffic to `/v2`.
- Concierge needs a retriever: the Weaviate hybrid search adapter and hosted reranker are not
  written, so the Concierge is not registered and knowledge questions get the "no reliable answer"
  template.
- Evaluator agent (LLM judge), Ragas runs, LangSmith tracing, and the background worker (summaries,
  memory extraction, consolidation) are not built; long-term memory exists as a tested library but
  is not yet called from the graph.
- Email/SMS OTP providers are not chosen; production senders raise until configured.
- The Redis checkpointer, Redis cache backend and HTTP tool backend are unit-tested against fakes
  only, not live services.
- The quote catalog (`CATALOG_PATH`), the "3 Es" funnel stages, the approval threshold, and the
  escalation destination and hours are placeholders pending business input.
- Per-user Google OAuth (legacy servers still share one token), the Railway service split, FastMCP
  evaluation (D16), indexer/OCR, payments.
- Python is pinned to 3.11+ in `pyproject.toml`; the dev machine currently runs 3.14.

## Decisions

See `docs/adr/0001-decisions.md`.
