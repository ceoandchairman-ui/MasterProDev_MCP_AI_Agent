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

## Data-subject requests

`privacy/dsr.py` exports or erases one person across Postgres (users, sessions, turns, leads, funnel events,
quotes, tool calls, escalations), the key-value store (vault, pending sign-ups, OTP, opt-out, rate keys) and the
long-term memory store, then writes an audit entry that holds only a hash of the user id. Operator tool:
`scripts/dsr.py`. Vendor deletion (Twilio, SendGrid, LangSmith, HuggingFace logs) is still manual and listed in the
report. Backups are not purged by erasure; they age out under the backup retention policy (not yet set).

## Google access (per user)

Each person connects their own Google account from `/v2/integrations/google/start` (verified users only). The
authorization uses a single-use state bound to the user, the refresh token is stored encrypted in `oauth_tokens`,
and a short-lived access token is cached encrypted for 50 minutes. The access token reaches the calendar and Gmail
servers only as the `X-Google-Access-Token` header for that one call; the servers never cache it. Without
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_OAUTH_REDIRECT_URI` the feature reports not configured and
the Comms agent asks the user to connect later. Placeholders only until the Google OAuth client exists.

## Wired into the chat path

`create()` builds one `ChatService` with: pseudonymization, response cache (shared answers only, never
anything with personal data or session tokens), long-term memory (consent required; recalled before the turn,
proposed after it), rolling summaries, escalation (record, staff email, assistant paused until resolved), per-agent
token metrics, durable tool-call audit, pseudonymized turn records, and an LLM egress guard that refuses raw
personal data, daily token budgets (per conversation and global), a sampled LLM judge that replaces unsupported
answers, and step-up verification for sensitive account actions. A single test (`tests/unit/test_end_to_end.py`) drives a whole journey through the real factory.

## Built and tested (356 tests)

Everything above and in the module map: five LLM agents with a fake model, the guarded tool executor, hybrid
retrieval with a fail-soft hosted reranker, account security (step-up, contact changes, export, deletion), per-user Google access, messaging and multi-channel gateway, SSE
streaming, account session management, data-subject export and erasure, golden routing and retrieval sets with an
offline runner, two Grafana dashboards, CI with an evaluation gate, deploy workflow, backup and restore scripts.
None of it has run against live Postgres, Redis, a language model or any provider.

## Not done (known gaps)

- **Never run live:** Postgres with pgvector (including the HNSW query), Redis (cache, KV, checkpointer), the
  embeddings and rerank endpoints, Twilio, SendGrid, Google OAuth, Railway. `deploy/railway/api.toml` stays at one
  replica until a two-replica test passes against the production database and Redis.
- **Thresholds are guesses:** `RETRIEVAL_MIN_SCORE` (0.35) and `RERANK_MIN_SCORE` (0.3) need tuning with
  `python scripts/run_evals.py --retrieval` against the real embedder. Test scores use a toy embedder.
- **Streaming is progressive display**, not token-level: the reply is produced whole, then split into sentences.
- **Cache hits skip the graph**, so a cached exchange is not added to that conversation's history.
- **Memory** stores text proposed by the model after validation; there is no consolidation job, entity tracking or
  knowledge graph. Embedding-based memory recall is not used (lexical overlap only).
- **Missing stories:** task decomposition and multi-agent handoff beyond the escalation packet (S6.8), edge and
  custom domain setup (S14.12), semantic cache (S16.3), voice and image input, OCR indexer, payments, inbound email
  and voice channels, entity tracking and memory consolidation jobs.
- **Vendor deletion** after an erasure request is manual; backups are not purged by erasure and need a retention
  policy. Vault retention (7 days) and conversation retention are placeholders.
- **Placeholders pending business input:** quote catalog (`CATALOG_PATH`), approval threshold, the "3 Es" stages,
  escalation inbox and hours, OTP and email providers, Twilio and Google credentials.
- **Legacy host** still runs the current product; `NEW_PIPELINE_PERCENT` (default 0) sends a share of its `/chat`
  traffic to the new pipeline once the new package is installed in that image.
- Python is pinned to 3.11+ in `pyproject.toml`; the dev machine currently runs 3.14.

## Decisions

See `docs/adr/0001-decisions.md`.
