variable "project_name" {
  description = "Railway project name"
  type        = string
  default     = "mpd-assistant"
}

variable "project_description" {
  description = "Railway project description"
  type        = string
  default     = "MasterProDev multi-agent conversational assistant"
}

variable "region" {
  description = "Railway region (us-west, us-east, eu-west, se-asia)"
  type        = string
  default     = "us-west"
}

variable "github_repo" {
  description = "GitHub repository (owner/repo format)"
  type        = string
  default     = "ceoandchairman-ui/MasterProDev_MCP_AI_Agent"
}

variable "github_branch" {
  description = "GitHub branch to deploy"
  type        = string
  default     = "ai-agent-mpd-dev-branch"
}

# Database secrets
variable "postgres_password" {
  description = "PostgreSQL password"
  type        = string
  sensitive   = true
}

variable "postgres_user" {
  description = "PostgreSQL user"
  type        = string
  default     = "mpd"
}

variable "postgres_db" {
  description = "PostgreSQL database name"
  type        = string
  default     = "mpd"
}

# Application secrets
variable "huggingface_api_key" {
  description = "HuggingFace API key"
  type        = string
  sensitive   = true
}

variable "secret_key" {
  description = "Application secret key"
  type        = string
  sensitive   = true
}

variable "data_encryption_key" {
  description = "Data encryption key (Fernet format)"
  type        = string
  sensitive   = true
}

variable "blind_index_key" {
  description = "Blind index key (Fernet format)"
  type        = string
  sensitive   = true
}

variable "mcp_service_key" {
  description = "MCP service key"
  type        = string
  sensitive   = true
}

variable "metrics_token" {
  description = "Metrics/observability token"
  type        = string
  sensitive   = true
}

# Models
variable "huggingface_model" {
  description = "HuggingFace model to use"
  type        = string
  default     = "meta-llama/Llama-2-7b-chat"
}

variable "llm_model_cheap" {
  description = "LLM model for cheap tier"
  type        = string
  default     = null
}

variable "llm_model_reasoning" {
  description = "LLM model for reasoning tier"
  type        = string
  default     = null
}

variable "llm_model_compress" {
  description = "LLM model for compression tier"
  type        = string
  default     = null
}

# Cost limits
variable "monthly_budget_usd" {
  description = "Monthly budget for Railway usage"
  type        = number
  default     = 90
}

variable "hard_limit_usd" {
  description = "Hard spending limit"
  type        = number
  default     = 150
}

variable "api_replicas" {
  description = "Number of API replicas"
  type        = number
  default     = 1
}

variable "public_domain" {
  description = "Public domain for API (optional)"
  type        = string
  default     = null
}
