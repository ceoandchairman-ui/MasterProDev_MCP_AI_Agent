# MasterProDev AI Assistant

Multi-agent conversational assistant (LangGraph, FastAPI, MCP tool servers, Postgres, Redis, Weaviate) hosted on Railway.

## Status

Under restructuring. The legacy application still lives in `mcp_host/` and `mcp_servers/` and is what the current Dockerfile runs. The new package is `src/mpd_assistant/`, migrated step by step behind the `USE_NEW_PIPELINE` flag.

## Layout

- `src/mpd_assistant/` new application package (core, api, graph, agents, routing, responses, memory, sessions, identity, privacy, cache, retrieval, tools, business, evaluation, observability, multimodal, ingestion, worker)
- `services/` MCP services (calendar, gmail, db, quoting)
- `mcp_host/`, `mcp_servers/` legacy code, removed once the new pipeline has parity
- `migrations/`, `evals/`, `observability/`, `deploy/`, `tests/`, `docs/`

## Develop

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
pytest
```

## Contributing

See `CONTRIBUTING.md` and `SECURITY.md`.
