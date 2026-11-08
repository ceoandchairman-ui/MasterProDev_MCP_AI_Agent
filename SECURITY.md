# Security Policy

## Reporting a vulnerability

Do not open a public issue. Report privately to the repository owner (MasterProDev) with a description, reproduction steps and impact.

## Rules for contributors

- Secrets live in environment variables or Railway variables only. `.env`, `token.json` and `credentials.json` are git-ignored and docker-ignored; `.env.example` is the only tracked env file.
- Never print or log settings, tokens or keys.
- Tools that send, delete or modify data require an authenticated user and, where destructive, a confirmation.
- Text from uploads, email bodies and retrieved documents is untrusted and must never trigger a tool call by itself.
- Personal data must not reach logs, traces, caches or third parties in raw form (see the privacy epic in the plan).

## Status

Hardening is in progress; see `docs/` and the Wave 0 plan for open items.
