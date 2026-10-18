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
| `messaging` | provider-agnostic outbound layer: Twilio (SMS, WhatsApp) and SendGrid wrappers, consent, rate/spend caps, idempotency, confirmations |
| `channels` | inbound normalization (Twilio webhooks with signature check), per-channel formatting, cross-channel identity by phone |
| `api` | v2 FastAPI app and the `create()` ASGI factory |

Legacy code (`mcp_host/`, `mcp_servers/`) still runs the current product and has been hardened
(service-key auth, role policy, escaped output, rate limits). It is removed after the new pipeline
reaches parity.

## Downstream communication

Everything outbound (OTP codes, booking confirmations, escalation notices, later follow-ups) goes through
`NotificationService`: template rendering in the user's locale, transactional vs marketing purpose,
consent and STOP/opt-out handling, per-target rate limit, daily spend cap, idempotency keys, metrics.
Providers are wrapped behind one interface: **Twilio** for SMS and WhatsApp, **SendGrid** for email.
Inbound SMS/WhatsApp arrive at `/v2/channels/twilio` (signature validated), are matched to a verified
user by phone blind index, and run through the same graph as the web widget. Not yet exercised against
live Twilio/SendGrid accounts; WhatsApp needs an approved sender.

## Built and tested (228 unit tests)

Everything in the module map, plus: LLM client (OpenAI-compatible, fallback), guarded tool executor
(permissions, confirmation, privacy-token rehydration at the tool boundary), five agents
(Concierge, Lead Conversion, Solution Architect, Quote, Comms & Scheduling) with Escalation handled
by the graph, the Alembic baseline, Grafana/Prometheus/OTel configs, CI workflow, `api.Dockerfile`
and Railway config. All agents are tested with a fake LLM; none has run against a live model.

## Not built yet (known gaps)

- Shared state now lives in Postgres (sessions, users, leads, funnel events) and Redis (OTP
  challenges, encrypted pending sign-ups, PII vault, caches, rate limits), and tests simulate two
  replicas on one database and store. It has **not been run against real Postgres/Redis**, so
  `deploy/railway/api.toml` stays at one replica and `/v2` should not take production traffic until
  a staging run with two replicas passes. In development an unreachable database or Redis falls
  back to process memory with a warning; production refuses to start instead.
- Vault retention (7 days) is a placeholder; messages stored in checkpoints keep tokens that stop
  resolving after the vault entry expires.
- Retrieval is pgvector + BM25 fused with RRF (`retrieval/pg.py`); the Concierge registers when an embedding key
  is set. The SQL path (HNSW vector query) and the embeddings endpoint are untested against real services, the
  hosted reranker is not written (a no-op reranker is used), and the Postgres on Railway must have the `vector`
  extension (pgvector image/template). Relevance thresholds (`RETRIEVAL_MIN_SCORE`, default 0.35) need tuning on
  a golden question set. Run `python scripts/seed_knowledge.py` after migrating to index `Company_Documents`.
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
