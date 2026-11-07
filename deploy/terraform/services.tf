# Volumes for stateful services
resource "railway_volume" "postgres" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "postgres-volume"
  mount_path     = "/var/lib/postgresql/data"
  size_gb        = 10
}

resource "railway_volume" "redis_state" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "redis-state-volume"
  mount_path     = "/data"
  size_gb        = 1
}

resource "railway_volume" "weaviate" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "weaviate-volume"
  mount_path     = "/var/lib/weaviate"
  size_gb        = 10
}

resource "railway_volume" "prometheus" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "prometheus-volume"
  mount_path     = "/prometheus"
  size_gb        = 5
}

resource "railway_volume" "grafana" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "grafana-volume"
  mount_path     = "/var/lib/grafana"
  size_gb        = 1
}

# ============================================================================
# DATABASE: PostgreSQL with pgvector
# ============================================================================
resource "railway_service" "postgres" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "postgres"

  deployment_config = {
    image              = "pgvector/pgvector:pg16"
    memory_mb          = 1024
    cpu_cores          = 1
    region             = local.region
    health_check_path  = "/health"
    health_check_timeout_seconds = 30
    port               = 5432
  }

  volumes = [
    {
      volume_id  = railway_volume.postgres.id
      mount_path = "/var/lib/postgresql/data"
    }
  ]

  environment_variables = {
    PGDATA           = "/var/lib/postgresql/data/pgdata"
    POSTGRES_DB      = var.postgres_db
    POSTGRES_USER    = var.postgres_user
  }

  sensitive_variables = {
    POSTGRES_PASSWORD = var.postgres_password
  }
}

# ============================================================================
# CACHE & CHECKPOINTS: Redis Stack
# ============================================================================
resource "railway_service" "redis_state" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "redis-state"

  deployment_config = {
    image              = "redis/redis-stack-server:7.4.0-v1"
    memory_mb          = 512
    cpu_cores          = 0.25
    region             = local.region
    port               = 6379
  }

  volumes = [
    {
      volume_id  = railway_volume.redis_state.id
      mount_path = "/data"
    }
  ]
}

# ============================================================================
# API SERVICE
# ============================================================================
resource "railway_service" "api" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "api"

  deployment_config = {
    build_command     = "docker build"
    dockerfile_path   = "deploy/dockerfiles/api.Dockerfile"
    memory_mb         = 1024
    cpu_cores         = 1
    region            = local.region
    replicas          = var.api_replicas
    health_check_path = "/health"
    health_check_timeout_seconds = 60
    pre_deploy_command = ["alembic", "upgrade", "head"]
    restart_policy    = "ON_FAILURE"
    restart_max_retries = 5
    port              = 8000
    public_port       = 443
  }

  github_source = {
    repo   = var.github_repo
    branch = var.github_branch
  }

  environment_variables = {
    ENV                  = "production"
    PORT                 = "8000"
    HUGGINGFACE_MODEL    = var.huggingface_model
    LOG_LEVEL            = "INFO"
    PYTHONUNBUFFERED     = "1"
  }

  sensitive_variables = {
    SECRET_KEY              = var.secret_key
    DATABASE_URL            = "postgresql://${var.postgres_user}:${var.postgres_password}@postgres.railway.internal:5432/${var.postgres_db}"
    REDIS_URL               = "redis://:@redis-state.railway.internal:6379/0"
    HUGGINGFACE_API_KEY     = var.huggingface_api_key
    DATA_ENCRYPTION_KEY     = var.data_encryption_key
    BLIND_INDEX_KEY         = var.blind_index_key
    MCP_SERVICE_KEY         = var.mcp_service_key
    METRICS_TOKEN           = var.metrics_token
  }

  # Conditional variables for optional model settings
  dynamic "environment_variables" {
    for_each = var.llm_model_cheap != null ? [1] : []
    content {
      LLM_MODEL_CHEAP = var.llm_model_cheap
    }
  }

  dynamic "environment_variables" {
    for_each = var.llm_model_reasoning != null ? [1] : []
    content {
      LLM_MODEL_REASONING = var.llm_model_reasoning
    }
  }

  dynamic "environment_variables" {
    for_each = var.llm_model_compress != null ? [1] : []
    content {
      LLM_MODEL_COMPRESS = var.llm_model_compress
    }
  }

  depends_on = [
    railway_service.postgres,
    railway_service.redis_state
  ]
}

# ============================================================================
# WORKER SERVICE
# ============================================================================
resource "railway_service" "worker" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "worker"

  deployment_config = {
    build_command   = "docker build"
    dockerfile_path = "deploy/dockerfiles/worker.Dockerfile"
    memory_mb       = 1024
    cpu_cores       = 1
    region          = local.region
    replicas        = 1
    restart_policy  = "ON_FAILURE"
    restart_max_retries = 5
    port            = 9000
  }

  github_source = {
    repo   = var.github_repo
    branch = var.github_branch
  }

  environment_variables = {
    ENV              = "production"
    PORT             = "9000"
    HUGGINGFACE_MODEL = var.huggingface_model
    PYTHONUNBUFFERED = "1"
  }

  sensitive_variables = {
    SECRET_KEY          = var.secret_key
    DATABASE_URL        = "postgresql://${var.postgres_user}:${var.postgres_password}@postgres.railway.internal:5432/${var.postgres_db}"
    REDIS_URL           = "redis://:@redis-state.railway.internal:6379/0"
    HUGGINGFACE_API_KEY = var.huggingface_api_key
    DATA_ENCRYPTION_KEY = var.data_encryption_key
    BLIND_INDEX_KEY     = var.blind_index_key
  }

  depends_on = [
    railway_service.postgres,
    railway_service.redis_state
  ]
}

# ============================================================================
# MCP SERVICES (Calendar, Gmail, DB, Quoting)
# ============================================================================
resource "railway_service" "mcp_calendar" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "mcp-calendar"

  deployment_config = {
    build_command   = "docker build"
    dockerfile_path = "services/mcp_calendar/Dockerfile"
    memory_mb       = 256
    cpu_cores       = 0.25
    region          = local.region
    replicas        = 1
    health_check_path = "/health"
    port            = 8001
  }

  github_source = {
    repo   = var.github_repo
    branch = var.github_branch
  }

  environment_variables = {
    PORT = "8001"
  }

  depends_on = [railway_service.api]
}

resource "railway_service" "mcp_gmail" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "mcp-gmail"

  deployment_config = {
    build_command   = "docker build"
    dockerfile_path = "services/mcp_gmail/Dockerfile"
    memory_mb       = 256
    cpu_cores       = 0.25
    region          = local.region
    replicas        = 1
    health_check_path = "/health"
    port            = 8002
  }

  github_source = {
    repo   = var.github_repo
    branch = var.github_branch
  }

  environment_variables = {
    PORT = "8002"
  }

  depends_on = [railway_service.api]
}

resource "railway_service" "mcp_db" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "mcp-db"

  deployment_config = {
    build_command   = "docker build"
    dockerfile_path = "services/mcp_db/Dockerfile"
    memory_mb       = 512
    cpu_cores       = 0.5
    region          = local.region
    replicas        = 1
    health_check_path = "/health"
    port            = 8003
  }

  github_source = {
    repo   = var.github_repo
    branch = var.github_branch
  }

  environment_variables = {
    PORT = "8003"
  }

  sensitive_variables = {
    DATABASE_URL = "postgresql://${var.postgres_user}:${var.postgres_password}@postgres.railway.internal:5432/${var.postgres_db}"
  }

  depends_on = [railway_service.postgres]
}

resource "railway_service" "mcp_quoting" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "mcp-quoting"

  deployment_config = {
    build_command   = "docker build"
    dockerfile_path = "services/mcp_quoting/Dockerfile"
    memory_mb       = 256
    cpu_cores       = 0.25
    region          = local.region
    replicas        = 1
    health_check_path = "/health"
    port            = 8004
  }

  github_source = {
    repo   = var.github_repo
    branch = var.github_branch
  }

  environment_variables = {
    PORT = "8004"
  }

  depends_on = [railway_service.api]
}

# ============================================================================
# OBSERVABILITY: Weaviate, OTel Collector, Prometheus, Grafana
# ============================================================================
resource "railway_service" "weaviate" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "weaviate"

  deployment_config = {
    image        = "semitechnologies/weaviate:latest"
    memory_mb    = 2048
    cpu_cores    = 1
    region       = local.region
    replicas     = 1
    port         = 8080
  }

  volumes = [
    {
      volume_id  = railway_volume.weaviate.id
      mount_path = "/var/lib/weaviate"
    }
  ]

  environment_variables = {
    PERSISTENCE_DATA_PATH = "/var/lib/weaviate"
  }
}

resource "railway_service" "otel_collector" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "otel-collector"

  deployment_config = {
    image     = "otel/opentelemetry-collector-contrib:latest"
    memory_mb = 256
    cpu_cores = 0.25
    region    = local.region
    port      = 4317  # OTLP gRPC
  }

  environment_variables = {
    GOGC = "80"
  }
}

resource "railway_service" "prometheus" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "prometheus"

  deployment_config = {
    image     = "prom/prometheus:latest"
    memory_mb = 512
    cpu_cores = 0.25
    region    = local.region
    port      = 9090
  }

  volumes = [
    {
      volume_id  = railway_volume.prometheus.id
      mount_path = "/prometheus"
    }
  ]

  environment_variables = {
    GOGC = "80"
  }
}

resource "railway_service" "grafana" {
  project_id     = local.project_id
  environment_id = local.environment_id
  name           = "grafana"

  deployment_config = {
    image              = "grafana/grafana:latest"
    memory_mb          = 256
    cpu_cores          = 0.25
    region             = local.region
    replicas           = 1
    port               = 3000
    public_port        = 443
  }

  volumes = [
    {
      volume_id  = railway_volume.grafana.id
      mount_path = "/var/lib/grafana"
    }
  ]

  environment_variables = {
    GF_SECURITY_ADMIN_PASSWORD = "admin"
    GF_INSTALL_PLUGINS        = ""
  }
}
