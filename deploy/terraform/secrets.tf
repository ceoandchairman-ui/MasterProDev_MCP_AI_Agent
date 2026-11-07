# Generated once and kept in Terraform state. Do not destroy the two Fernet keys: data already encrypted with them
# would become unreadable (see docs/runbooks/key-rotation.md for rotation).
resource "random_bytes" "data_encryption_key" {
  length = 32

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_bytes" "blind_index_key" {
  length = 32

  lifecycle {
    prevent_destroy = true
  }
}

resource "random_password" "secret_key" {
  length  = 48
  special = false
}

resource "random_password" "mcp_service_key" {
  length  = 48
  special = false
}

resource "random_password" "metrics_token" {
  length  = 32
  special = false
}

locals {
  # Fernet wants url-safe base64 of 32 bytes.
  data_encryption_key = replace(replace(random_bytes.data_encryption_key.base64, "+", "-"), "/", "_")
  blind_index_key     = replace(replace(random_bytes.blind_index_key.base64, "+", "-"), "/", "_")
}
