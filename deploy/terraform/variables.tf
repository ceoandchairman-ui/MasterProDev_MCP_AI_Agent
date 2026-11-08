variable "project_name" {
  type    = string
  default = "mpd-assistant"
}

variable "github_repo" {
  description = "owner/repo that Railway builds the app services from"
  type        = string
  default     = "ceoandchairman-ui/MasterProDev_MCP_AI_Agent"
}

variable "github_branch" {
  type    = string
  default = "ai-agent-mpd-dev-branch"
}

variable "backend_subdomain" {
  description = "Subdomain on up.railway.app for assistant-backend (must be unique across Railway)"
  type        = string
  default     = "mpd-assistant-backend"
}

variable "cors_origins" {
  description = "Comma-separated site origins allowed to call the backend from a browser (the sites that embed the widget)"
  type        = string
  default     = "https://masterprodev.com,https://www.masterprodev.com"
}

variable "mcp_db_url" {
  description = "Connection string for the read-only Postgres role used by mcp-db. Leave null until that role exists: mcp-db is not created without it."
  type        = string
  default     = null
  sensitive   = true
}

variable "huggingface_api_key" {
  type      = string
  default   = null
  sensitive = true
}

variable "model_settings" {
  description = "Model names, e.g. HUGGINGFACE_MODEL, LLM_MODEL_CHEAP, LLM_MODEL_REASONING, LLM_MODEL_COMPRESS, EMBEDDING_MODEL"
  type        = map(string)
  default     = {}
}

variable "extra_backend_secrets" {
  description = "Optional provider secrets for assistant-backend, e.g. TWILIO_ACCOUNT_SID, SENDGRID_API_KEY, GOOGLE_CLIENT_SECRET, STRIPE_SECRET_KEY"
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "extra_worker_secrets" {
  description = "Optional extra secrets for the worker (for example embedding endpoint keys)"
  type        = map(string)
  default     = {}
  sensitive   = true
}
