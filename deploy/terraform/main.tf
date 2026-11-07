terraform {
  required_version = ">= 1.0"
  required_providers {
    railway = {
      source  = "railwayapp/railway"
      version = "~> 0.1.0"
    }
  }
}

provider "railway" {
  # Railway API token should be set via RAILWAY_TOKEN environment variable
}

# Main project - mpd-assistant
resource "railway_project" "mpd" {
  name        = var.project_name
  description = var.project_description
}

# Production environment
resource "railway_environment" "production" {
  project_id = railway_project.mpd.id
  name       = "production"
}

# Data source to reference the environment for policies/settings
locals {
  project_id     = railway_project.mpd.id
  environment_id = railway_environment.production.id
  region         = var.region
}
