# Railway service layout (target)

Single environment (production). Deploys go straight to it, so the gates are CI, the restore drill and the
migration check, run before each deploy.

One Railway service per process. Only `api` has a public domain; everything else is reached over Railway private
networking (`<service>.railway.internal`).

| Service | Source | Public | Replicas | Notes |
|---|---|---|---|---|
| api | deploy/dockerfiles/api.Dockerfile | yes | 1 until a two-replica test passes | /health for healthcheck |
| postgres | Railway Postgres with the pgvector extension | no | 1 | run `CREATE EXTENSION vector` if the app role cannot |
| redis | Railway Redis (Redis Stack when checkpoints are enabled) | no | 1 | state, OTP, vault, caches, rate limits |
| mcp-calendar | mcp_servers/calendar_server (legacy image) | no | 1 | requires MCP_SERVICE_KEY |
| mcp-gmail | mcp_servers/gmail_server (legacy image) | no | 1 | requires MCP_SERVICE_KEY |
| worker | later: scripts/seed_knowledge.py as a job | no | 0 (job) | run on demand, idempotent |
| otel-collector | observability/otel-collector | no | 1 | |
| prometheus | observability/prometheus | no | 1 | volume for TSDB |
| grafana | observability/grafana | yes (login) | 1 | volume for state |

Shared variables are referenced, not copied: `DATABASE_URL=${{postgres.DATABASE_URL}}`,
`REDIS_URL=${{redis.REDIS_URL}}`, `CALENDAR_SERVER_URL=http://mcp-calendar.railway.internal:8000`.
Secrets (keys, MCP_SERVICE_KEY, METRICS_TOKEN, DATA_ENCRYPTION_KEY, BLIND_INDEX_KEY) live only in Railway variables.
