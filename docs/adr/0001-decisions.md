# ADR 0001: Founding decisions

| # | Decision | Status |
|---|---|---|
| D1 | Seven LLM agents (Concierge, Lead Conversion, Solution Architect, Quote, Comms & Scheduling, Escalation, Evaluator); supervisor, payment, record writer, cache and session manager are components | Proposed |
| D2 | Response modes templated / generated / reasoned with a ladder to escalation | Implemented (router, modes) |
| D3 | Postgres is the source of truth; Redis (state and cache as separate services) is disposable | Proposed |
| D4 | No read replicas or HA at launch; backups and fail-soft behavior | Proposed |
| D9 | Strangler migration: new pipeline beside the legacy host, legacy removed at parity | In progress |
| D11 | Reversible pseudonymization with an encrypted per-session vault | Implemented |
| D12 | Detector fails closed at storage and telemetry boundaries | Partly (telemetry scrubbing, evaluator) |
| D14 | Visitors get FAQ-only answers until email and phone are verified | Implemented as default (open for owner decision) |
| D15 | Passwordless email OTP plus SMS OTP; staff use stronger auth | Implemented for users |
| D16 | Evaluate FastMCP for new MCP services after the security work | Open |

Open owner decisions: funnel stage rules, price catalog and approver, payment scope, escalation
destination and hours, first languages, model choices, retention periods, OTP providers and spend
cap, whether third-party LLMs may receive raw PII (default: no).
