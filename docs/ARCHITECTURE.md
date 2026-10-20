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
| `services` (repo root) | tool services, one image each: Calendar, Gmail, company data, quoting; shared base in `services/_common` |

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

## Built and tested (run `pytest tests/unit tests/privacy` for the current count)

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
- **Memory** stores text proposed by the model after validation. Entity and topic tracking, episodic memory (written when
  a conversation ends in escalation or is closed with `POST /v2/session/{id}/end`), approved reply patterns (staff review
  them in the console), the memory tools, the nightly consolidation job and embedding-based recall are wired. The
  knowledge-graph memory is not built.
- **Wired into `api/app.py` and covered by unit tests, never run live:** payments (stored quotes, Stripe checkout, signed
  webhook, receipt email), staff review of quotes the pricing rules held back (`/v2/admin/quotes`; before this nothing could
  make such a quote payable), uploads and OCR (also used by the worker's reindex job), voice (speech endpoints and the Twilio
  Voice channel), inbound email, the staff console (`/admin`) and admin routes, delivery tracking (Twilio status callback,
  SendGrid event webhook, retries for transient failures, a dead-letter list), per-IP edge limiting and CORS, entity and
  topic notes in the prompt, uploaded-file context and approved style examples.
- **Tool services** (`services/`): Calendar and Gmail run per-user on the caller's Google token, with time-zone-aware
  events, free-slot search, rescheduling, drafts, idempotency keys and short error codes; the company-data service answers
  allowlisted read-only queries (lead stage, quotes, customer profile with company, never name, email or phone); the quoting
  service stays stateless. Every tool is declared once in `tools/registry.py` with its arguments: the planner is shown them,
  the Comms agent rejects bad arguments before anything runs, and the executor, not the model, supplies `user_id` and idempotency keys.
- **Limits and resilience** (all configurable in `core/config.py`, defaults in `.env.example`):
  - *Per turn:* one conversation turn may take `TURN_TIMEOUT_SECONDS` (45); past that the user gets the retry message. The graph
    has an explicit `GRAPH_RECURSION_LIMIT` (30; the real maximum is about 12): at most 3 sub-tasks per message, the supervisor
    escalates after 6 visits, the plan-act-reflect loop runs at most 2 times for the Solution Architect, Comms plans at most
    3 actions. A loop-limit stop hands the conversation to a person.
  - *Model calls:* each tier (cheap, mid, reasoning) has its own endpoint, key, timeout, circuit breaker and optional fallback
    model (`LLM_<TIER>_*`, `LLM_FALLBACK_<TIER>`). Transient failures (429, 5xx, timeouts) are retried with backoff and jitter,
    honouring `Retry-After`; permanent refusals (401, 402, 400) fail at once. A request the provider rejects as malformed
    never opens the circuit. At most `LLM_MAX_CONCURRENCY` calls per tier run at once.
  - *Tool calls:* each tool service has its own circuit breaker. Read-only tools are retried; sends, event changes and deletes
    never are. Calls run at most `TOOL_MAX_CONCURRENCY` at a time. Writes also have per-user daily limits
    (`ToolSpec.limit_per_day`, shared across a person's sessions), and a repeated confirmed action is neither repeated nor counted.
  - *Event loop:* blocking Postgres and Redis calls in the chat path run on a thread pool (`THREADPOOL_SIZE`), handlers that
    never await are plain functions, and every Redis and Postgres call is time-bounded (2 s sockets, 15 s statements, 5 s waiting
    for a pooled connection). The remaining blocking calls (key-value reads inside `ChatService`) are short and bounded; a full
    async rewrite (`asyncpg`, `redis.asyncio`) is the next step if `scripts/load_test.py` shows the loop is the limit. Run more
    than one worker with `WEB_CONCURRENCY` (uvicorn reads it) so one slow process cannot stall every request.
- **Prompts and context:** every prompt, including the judge, summariser and memory prompts, is a versioned file under
  `agents/*/prompts/` and its version is part of the cache key. The Concierge, Comms and Lead agents carry the last few turns
  (trimmed to a per-agent budget), and the Concierge turns a follow-up such as "and how long does it take?" into a standalone
  search query with one cheap model call. Background notes (summary, memories, files, style) are fitted to a token budget:
  uploaded-file text and style examples are dropped first, then the least relevant memories, and references such as "that
  email" are never dropped. `scripts/compare_models.py` measures candidate models on the project's own prompts.
- **Human approval** is checkpointed state (`pending_action`), not a LangGraph `interrupt()`: sends, event changes and
  payments wait for an explicit yes on the next turn, and the checkpointer keeps the question across restarts.
- **Also written, not run live:** key rotation (`privacy/rotation.py`, `scripts/rotate_keys.py`, `DATA_ENCRYPTION_KEYS_PREVIOUS`),
  a load-test tool (`scripts/load_test.py`) and runbooks (`docs/runbooks/`).
- **Gap-closing batch:** versioned prompt registry (S2.7); the Solution Architect runs through the bounded plan-act-reflect
  subgraph (S6.0); tool-call idempotency, a shared read-tool cache and tool-result offloading (S5.5, S16.4, S19.4); a retrieval
  cache and per-agent document scopes (S7.4, S7.3); admin cache purge (S16.5); prompt-prefix stability metric (S19.9); audited
  staff lookup, duplicate detection and merge of people (S21.7, S19.14); failure-mode handling (S14.13); new alert rules.
- **Done and tested:** semantic cache (S16.3), task decomposition across agents (S6.8), the per-turn state reset
  (a conversation used to be escalated to a person on its seventh message), memory evaluation with a golden set
  (`python scripts/run_evals.py --memory`, S19.25), and the memory-recall noise fix it exposed (an unrelated question
  could recall a memory because both contained "the"; recall now compares content words with a minimum match).
- **Metric wired:** `mpd_pii_detections_total` was defined but never incremented; it now counts raw personal data
  refused at the model boundary (`B2_llm_egress`) and found in replies (`B7_reply`).
- **Railway topology (S14.2, S14.3, S14.10, S14.12):** `deploy/railway/topology.yaml` lists environments, public and private
  services, volumes, resource caps and cost limits; `deploy/railway/edge.yaml` lists the domain, TLS and edge settings.
  `scripts/check_railway_topology.py` checks them against the service tomls. The domains are placeholders, and the dashboard
  still has to be set to match.
- **Still missing:** the knowledge-graph memory (optional, only if flat memory fails the evaluation); a browser test of the
  widget and the console (their scripts are syntax-checked and statically tested only); the cutover from the legacy host
  (`NEW_PIPELINE_PERCENT` is 0) and everything under "Never run live" above.
- **Legacy MCP servers** in `mcp_servers/` still run in the root `Dockerfile` container, `docker/docker-compose.yml` and
  `tests/integration/test_mcp_servers.py`. The new Calendar and Gmail services in `services/` are what the Railway tomls
  build; the legacy copies go when the legacy container is retired.
- **The company-data database role** (`MCP_DB_URL`) needs `SELECT` on `companies` as well as users, leads and quotes (migration 0007).
- **One-off jobs:** `python -m mpd_assistant.worker.main --once reindex` replaces the legacy seeder (`seed.py`), including OCR
  of scanned documents when `OCR_ENGINE` is set; `--once retention` and `--once consolidate` run the other jobs.
- **Vendor deletion** after an erasure request is manual; backups are not purged by erasure and need a retention
  policy. Vault retention (7 days) and conversation retention are placeholders.
- **Placeholders pending business input:** quote catalog (`CATALOG_PATH`), approval threshold, the "3 Es" stages,
  escalation inbox and hours, OTP and email providers, Twilio and Google credentials.
- **Legacy host** still runs the current product; `NEW_PIPELINE_PERCENT` (default 0) sends a share of its `/chat`
  traffic to the new pipeline once the new package is installed in that image.
- Python is pinned to 3.11+ in `pyproject.toml`; the dev machine currently runs 3.14.

## Decisions

See `docs/adr/0001-decisions.md`.
