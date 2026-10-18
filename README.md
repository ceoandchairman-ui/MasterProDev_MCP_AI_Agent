# MasterProDev Multi-Agent AI Assistant

A multilingual, multimodal conversational AI assistant built with LangGraph, PostgreSQL, and full observability. The system orchestrates seven specialized agents to qualify leads, schedule meetings, draft project scopes, and handle escalations.

## Features

- **7 LLM Agents**: Concierge, Lead Conversion, Solution Architect, Quote, Comms & Scheduling, Escalation, Evaluator
- **Response Modes**: Templated (fast), Generated (flexible), Reasoned (ReAct with planning)
- **Multi-Turn Memory**: Short-term and long-term with consent and governance
- **PII Protection**: Reversible pseudonymization and boundary enforcement
- **User Verification**: Passwordless email OTP + SMS OTP
- **Observability**: OpenTelemetry, Grafana, LangSmith, Ragas metrics
- **Caching**: Exact-match, semantic, and tool-result caching
- **Shared MCP Tools**: Calendar, Gmail, DB, Quoting (per-user OAuth)
- **Hosted on Railway**: Production-ready infrastructure

## Quick Start

### Install
`ash
pip install -e ".[dev]"
`

### Configure
`ash
cp .env.example .env
`

### Run
`ash
docker-compose -f deploy/compose.dev.yml up -d
alembic upgrade head
uvicorn mpd_assistant.api.main:app --reload
`

## Project Structure

See docs/ARCHITECTURE.md for the detailed system design.

## License

MIT
