locals {
  hf_variables    = var.huggingface_api_key == null ? [] : [{ name = "HUGGINGFACE_API_KEY", value = var.huggingface_api_key }]
  model_variables = [for k, v in var.model_settings : { name = k, value = v }]

  mcp_urls = merge(
    {
      CALENDAR_SERVER_URL = "http://mcp-calendar.railway.internal:8001"
      GMAIL_SERVER_URL    = "http://mcp-gmail.railway.internal:8002"
    },
    local.mcp_db_enabled ? { DB_SERVER_URL = "http://mcp-db.railway.internal:8004" } : {}
  )

  storage_variables = [
    { name = "DATABASE_URL", value = local.database_url },
    { name = "REDIS_URL", value = local.redis_url },
    { name = "DATA_ENCRYPTION_KEY", value = local.data_encryption_key },
    { name = "BLIND_INDEX_KEY", value = local.blind_index_key },
    { name = "SECRET_KEY", value = random_password.secret_key.result },
  ]
}

# Public service: chat API, identity, tool calls, webhooks, payments, staff console.
resource "railway_service" "backend" {
  project_id         = local.project_id
  name               = "assistant-backend"
  source_repo        = var.github_repo
  source_repo_branch = var.github_branch
  dockerfile_path    = "deploy/dockerfiles/api.Dockerfile"

  predeploy_command          = "alembic upgrade head"
  healthcheck_path           = "/health"
  healthcheck_timeout        = 60
  restart_policy_type        = "ON_FAILURE"
  restart_policy_max_retries = 5
}

resource "railway_service_domain" "backend" {
  environment_id = local.environment_id
  service_id     = railway_service.backend.id
  subdomain      = var.backend_subdomain
  target_port    = 8000
}

resource "railway_variable_collection" "backend" {
  environment_id = local.environment_id
  service_id     = railway_service.backend.id

  variables = concat(
    [
      { name = "ENV", value = "production" },
      { name = "PORT", value = "8000" },
      { name = "PUBLIC_DOMAIN", value = "https://${railway_service_domain.backend.domain}" },
      { name = "CORS_ORIGINS", value = var.cors_origins },
      { name = "MCP_SERVICE_KEY", value = random_password.mcp_service_key.result },
      { name = "METRICS_TOKEN", value = random_password.metrics_token.result },
    ],
    local.storage_variables,
    [for k, v in local.mcp_urls : { name = k, value = v }],
    local.hf_variables,
    local.model_variables,
    [for k, v in var.extra_backend_secrets : { name = k, value = v }],
  )
}

# Background jobs only (retention, memory consolidation, reindex). No port.
resource "railway_service" "worker" {
  project_id         = local.project_id
  name               = "worker"
  source_repo        = var.github_repo
  source_repo_branch = var.github_branch
  dockerfile_path    = "deploy/dockerfiles/worker.Dockerfile"

  restart_policy_type        = "ON_FAILURE"
  restart_policy_max_retries = 5
}

resource "railway_variable_collection" "worker" {
  environment_id = local.environment_id
  service_id     = railway_service.worker.id

  variables = concat(
    [{ name = "ENV", value = "production" }],
    local.storage_variables,
    local.hf_variables,
    local.model_variables,
    [for k, v in var.extra_worker_secrets : { name = k, value = v }],
  )
}

# Private tool services.
resource "railway_service" "mcp" {
  for_each = local.mcp_services

  project_id         = local.project_id
  name               = each.key
  source_repo        = var.github_repo
  source_repo_branch = var.github_branch
  dockerfile_path    = "services/${each.value.dir}/Dockerfile"

  healthcheck_path           = "/health"
  healthcheck_timeout        = 60
  restart_policy_type        = "ON_FAILURE"
  restart_policy_max_retries = 5
}

resource "railway_variable_collection" "mcp" {
  for_each = local.mcp_services

  environment_id = local.environment_id
  service_id     = railway_service.mcp[each.key].id

  variables = concat(
    [
      { name = "PORT", value = tostring(each.value.port) },
      { name = "MCP_SERVICE_KEY", value = random_password.mcp_service_key.result },
    ],
    each.key == "mcp-db" ? [{ name = "MCP_DB_URL", value = var.mcp_db_url }] : [],
  )
}
