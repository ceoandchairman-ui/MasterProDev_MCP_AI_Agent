terraform {
  required_version = ">= 1.5"

  required_providers {
    railway = {
      source  = "terraform-community-providers/railway"
      version = "0.6.3"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

# Authenticates with the RAILWAY_TOKEN environment variable (an account or workspace token).
provider "railway" {}

resource "railway_project" "mpd" {
  name        = var.project_name
  description = "MasterProDev multi-agent conversational assistant"
}

resource "railway_environment" "production" {
  project_id = railway_project.mpd.id
  name       = "production"
}

locals {
  project_id     = railway_project.mpd.id
  environment_id = railway_environment.production.id

  # Railway resolves ${{service.VAR}} references itself, so no database password passes through Terraform.
  database_url = "postgresql://$${{postgres.POSTGRES_USER}}:$${{postgres.POSTGRES_PASSWORD}}@$${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/$${{postgres.POSTGRES_DB}}"
  redis_url    = "redis://$${{redis-state.RAILWAY_PRIVATE_DOMAIN}}:6379/0"

  mcp_db_enabled = nonsensitive(var.mcp_db_url != null)

  # Ports are fixed in each service's Dockerfile CMD; PORT is set to match so Railway's health check probes the right one.
  mcp_services = merge(
    {
      "mcp-calendar" = { dir = "mcp_calendar", port = 8001 }
      "mcp-gmail"    = { dir = "mcp_gmail", port = 8002 }
    },
    local.mcp_db_enabled ? { "mcp-db" = { dir = "mcp_db", port = 8004 } } : {}
  )
}
