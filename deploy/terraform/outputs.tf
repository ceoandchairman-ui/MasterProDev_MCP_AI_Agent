output "backend_url" {
  value = "https://${railway_service_domain.backend.domain}"
}

output "service_ids" {
  value = merge(
    {
      postgres          = railway_service.postgres.id
      redis-state       = railway_service.redis_state.id
      assistant-backend = railway_service.backend.id
      worker            = railway_service.worker.id
    },
    { for k, s in railway_service.mcp : k => s.id }
  )
}
