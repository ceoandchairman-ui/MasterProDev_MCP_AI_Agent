# Railway infrastructure (Terraform)

Manages the `mpd-assistant` Railway project with the community provider `terraform-community-providers/railway` (pinned to 0.6.3).

## What it manages

| Service | Source | Exposure |
|---|---|---|
| `postgres` (pgvector pg16, 5 GB volume) | image, imported | private |
| `redis-state` (Redis Stack, 1 GB volume) | image, imported | private |
| `assistant-backend` | `deploy/dockerfiles/api.Dockerfile`, port 8000, pre-deploy `alembic upgrade head` | public domain |
| `worker` | `deploy/dockerfiles/worker.Dockerfile`, no port | private |
| `mcp-calendar` 8001, `mcp-gmail` 8002 | `services/*/Dockerfile` | private |
| `mcp-db` 8004 | created only when `mcp_db_url` is set | private |

Secrets (`SECRET_KEY`, both Fernet keys, `MCP_SERVICE_KEY`, `METRICS_TOKEN`) are generated in `secrets.tf` and stay in state. The two Fernet keys are `prevent_destroy`: data encrypted with them is unreadable without them. The Postgres password is not in Terraform; services receive it through Railway's `${{postgres.POSTGRES_PASSWORD}}` reference.

## What it does not manage

CPU and memory caps, spend limits and usage alerts (dashboard or `railway usage limit set`; record them in `deploy/railway/topology.yaml`), volume size, sealed variables, observability services, backups.

## Use

1. Create a Railway account or workspace token and export it: `RAILWAY_TOKEN`.
2. `cp terraform.tfvars.example terraform.tfvars` and edit.
3. `terraform init`, `terraform validate`.
4. `terraform plan`: the four `import` blocks in `imports.tf` must adopt the existing project, environment, `postgres` and `redis-state` with no destroy. The import ID formats and region names are unverified until this first plan.
5. Review, then `terraform apply` (separate approval).

State holds every generated secret in plaintext. It is git-ignored; move to an encrypted remote backend before real data goes in.
