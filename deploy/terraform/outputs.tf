output "project_id" {
  description = "Railway project ID"
  value       = railway_project.mpd.id
}

output "environment_id" {
  description = "Railway environment ID"
  value       = railway_environment.production.id
}

# ============================================================================
# Service Endpoints
# ============================================================================
output "api_service_id" {
  description = "API service ID"
  value       = railway_service.api.id
}

output "api_private_url" {
  description = "API private URL (within Railway network)"
  value       = "http://api.railway.internal:8000"
}

output "api_public_url" {
  description = "API public URL"
  value       = try(railway_service.api.public_domain, "https://api-production-*.up.railway.app")
}

output "worker_private_url" {
  description = "Worker private URL"
  value       = "http://worker.railway.internal:9000"
}

output "mcp_services" {
  description = "MCP service endpoints"
  value = {
    calendar = "http://mcp-calendar.railway.internal:8001"
    gmail    = "http://mcp-gmail.railway.internal:8002"
    db       = "http://mcp-db.railway.internal:8003"
    quoting  = "http://mcp-quoting.railway.internal:8004"
  }
}

# ============================================================================
# Database Connections
# ============================================================================
output "postgres_connection" {
  description = "PostgreSQL connection string (internal)"
  value       = "postgresql://${var.postgres_user}:****@postgres.railway.internal:5432/${var.postgres_db}"
  sensitive   = true
}

output "redis_connection" {
  description = "Redis connection string (internal)"
  value       = "redis://:@redis-state.railway.internal:6379/0"
}

# ============================================================================
# Observability
# ============================================================================
output "prometheus_url" {
  description = "Prometheus private URL"
  value       = "http://prometheus.railway.internal:9090"
}

output "grafana_url" {
  description = "Grafana public URL"
  value       = try(railway_service.grafana.public_domain, "https://grafana-production-*.up.railway.app")
}

output "weaviate_url" {
  description = "Weaviate private URL"
  value       = "http://weaviate.railway.internal:8080"
}

output "otel_collector_endpoint" {
  description = "OpenTelemetry collector endpoint"
  value       = "otel-collector.railway.internal:4317"
}

# ============================================================================
# Cost Information
# ============================================================================
output "cost_config" {
  description = "Cost configuration"
  value = {
    monthly_budget_usd = var.monthly_budget_usd
    hard_limit_usd     = var.hard_limit_usd
  }
}

# ============================================================================
# Network Info
# ============================================================================
output "private_network_pattern" {
  description = "Private network host pattern for services"
  value       = "{service}.railway.internal"
}

output "public_services" {
  description = "Publicly accessible services"
  value       = ["api", "grafana"]
}
