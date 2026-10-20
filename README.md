# MasterProDev AI Assistant

A multi-agent conversational assistant for MasterProDev: it answers questions from company documents, qualifies leads, books calls, drafts scopes and quotes, takes payment through Stripe-hosted checkout, and hands over to a person when it should. Built on LangGraph, FastAPI, Postgres with pgvector, and Redis, and hosted on Railway.

## Status

Under restructuring. The legacy application in `mcp_host/` and `mcp_servers/` still serves production traffic. The new package, `src/mpd_assistant/`, is complete in code and covered by unit tests, but has not yet been run against live Postgres, Redis, a language model, or any provider. `docs/ARCHITECTURE.md` lists what is wired, what is not, and what has never run live.

## Layout

- `src/mpd_assistant/` the application: core, api (and the staff console under `api/static/admin`), graph, agents, routing, responses, memory, sessions, identity, privacy, cache, retrieval, tools, business, evaluation, observability, multimodal, ingestion, messaging, channels, worker
- `services/` tool services, one image each: Calendar, Gmail, company data, quoting (shared base in `services/_common`)
- `web/widget/` the embeddable chat widget (no dependencies)
- `mcp_host/`, `mcp_servers/` legacy code, removed once the new pipeline has parity
- `migrations/`, `evals/`, `observability/`, `deploy/`, `scripts/`, `tests/`, `docs/`

## Develop

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; use source .venv/bin/activate elsewhere
pip install -e ".[dev]"
cp .env.example .env
pytest tests/unit tests/privacy tests/security
ruff check src services tests/unit tests/privacy scripts
```

Unit tests use fakes and in-memory SQLite, so they need no running services.

## Run against real services

```bash
python scripts/dev_env.py                                       # once: local secrets in .env.dev (git-ignored)
docker compose -f deploy/compose.dev.yml up -d --wait           # Postgres with pgvector + Redis Stack, schema migrated
pytest tests/integration/test_live_stack.py -m live -v          # migrations, vector search, checkpointer, a full conversation, payments
docker compose -f deploy/compose.dev.yml --profile app up -d --build     # also the api and worker
python scripts/smoke_test.py http://localhost:8000              # is it up, and are the right doors shut
```

To choose between candidate models, `python scripts/compare_models.py --tier reasoning --models a,b` runs the project's own prompts through each and prints a pass rate and speed per model (it makes real, billed calls).

Add `--profile tools` to start the four tool services. The first image pull needs a few hundred MB of free disk. Provider keys (language model, Twilio, SendGrid, Stripe, Google) go in `.env.dev`; features without a key switch themselves off.

## Deploy

Railway, one service per process. `deploy/railway/topology.yaml` lists the services, volumes, resource caps and cost limits, and `scripts/check_railway_topology.py` checks it against the service configs. Runbooks for incidents, key rotation and restore are in `docs/runbooks/`.

## Contributing

See `CONTRIBUTING.md` and `SECURITY.md`.
