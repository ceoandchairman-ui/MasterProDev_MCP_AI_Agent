# Postgres variables (user, database, password) already exist in Railway and are deliberately not managed here:
# the password was fixed when the volume was first initialised and must not change.
resource "railway_service" "postgres" {
  project_id   = local.project_id
  name         = "postgres"
  source_image = "pgvector/pgvector:pg16"

  volume = {
    name       = "postgres-volume"
    mount_path = "/var/lib/postgresql/data"
  }
}

# Redis Stack, not plain Redis: the LangGraph checkpointer needs the RediSearch and JSON modules.
resource "railway_service" "redis_state" {
  project_id   = local.project_id
  name         = "redis-state"
  source_image = "redis/redis-stack-server:7.4.0-v1"

  volume = {
    name       = "redis-state-volume"
    mount_path = "/data"
  }
}
