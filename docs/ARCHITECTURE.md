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
| `retrieval`, `evaluation` | RRF fusion + grounding; online rules + offline agentic metrics |
| `observability` | Prometheus metrics, OTel setup with scrubbing |
| `api` | v2 FastAPI app and the `create()` ASGI factory |

Legacy code (`mcp_host/`, `mcp_servers/`) still runs the current product and has been hardened
(service-key auth, role policy, escaped output, rate limits). It is removed after the new pipeline
reaches parity.

## Built and tested (150 unit tests)

Everything in the module map above, the Alembic baseline (`migrations/versions/0001`), Grafana
dashboard + Prometheus/OTel configs, CI workflow, and the `api.Dockerfile` / Railway config.

## Not built yet (known gaps)

- Sessions, PII vault and user records are **process memory** in the new API. Until Postgres/Redis
  repositories replace them, run **one replica** (set in `deploy/railway/api.toml`) and do not
  route production traffic to `/v2`.
- No LLM-backed agents yet: the graph runs templates, identity gating, escalation and a stub for
  every agent. Agents (prompts, PRAR wiring, tool calls through MCP) are the next wave.
- Email/SMS OTP providers are not chosen; production senders raise until configured.
- Real retrieval backend (Weaviate hybrid + hosted reranker), Redis cache backend wiring, and the
  Redis checkpointer have not been exercised against live services (Redis checkpointer code path
  falls back to memory in development only).
- Quote catalog and prices, the "3 Es" funnel stages, approval threshold, escalation destination
  and hours are placeholders pending business input.
- Per-user Google OAuth (legacy servers still use one shared token), Railway service split,
  Ragas runs, LangSmith, indexer/OCR, payments.
- Python is pinned to 3.11+ in `pyproject.toml`; the dev machine currently runs 3.14.

## Decisions

See `docs/adr/0001-decisions.md`.
