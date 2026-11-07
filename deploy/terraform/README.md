# Railway Infrastructure as Code (Terraform)

This directory contains Terraform configuration to manage the complete Railway infrastructure for the MasterProDev multi-agent assistant.

## Overview

The Terraform files codify all Railway resources including:
- **Project & Environment**: mpd-assistant project with production environment
- **Services**: API, Worker, MCP services (Calendar, Gmail, DB, Quoting), Observability stack
- **Databases & Cache**: PostgreSQL with pgvector, Redis Stack (state & cache)
- **Volumes**: Persistent storage for stateful services
- **Networking**: Private networking between services, public endpoints for API and Grafana
- **Secrets**: Sensitive variables for database, API keys, encryption keys

## Files

- `main.tf` - Provider configuration and project setup
- `variables.tf` - Input variables with descriptions and defaults
- `services.tf` - All service definitions (compute, databases, observability)
- `outputs.tf` - Output values (URLs, connection strings, etc.)
- `terraform.tfvars.example` - Example variables file

## Prerequisites

1. **Railway API Token**: Set via environment variable
   ```bash
   export RAILWAY_TOKEN="your_api_token_here"
   ```

2. **Terraform >= 1.0**
   ```bash
   terraform --version
   ```

3. **Railway Provider**: Installed automatically via `terraform init`

## Usage

### 1. Initialize Terraform

```bash
cd deploy/terraform
terraform init
```

This downloads the Railway provider and initializes the working directory.

### 2. Prepare Variables

Copy the example file and customize:

```bash
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with actual values
```

**Critical values to set**:
- `postgres_password` - Generate a strong password
- `huggingface_api_key` - From your HF account
- `secret_key` - Generate with: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- `data_encryption_key` - Fernet format: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `blind_index_key` - Fernet format: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `mcp_service_key` - Generate with: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- `metrics_token` - Generate with: `python3 -c "import secrets; print(secrets.token_urlsafe(16))"`

### 3. Plan the Deployment

Review what Terraform will create:

```bash
terraform plan -out=tfplan
```

This shows all resources that will be created. Review carefully before applying.

### 4. Apply the Configuration

Deploy to Railway:

```bash
terraform apply tfplan
```

This will:
- Create the Railway project and environment
- Create all services with proper configuration
- Set up volumes and networking
- Configure environment variables and secrets
- Establish service dependencies

**Estimated time**: 5-10 minutes for initial deployment

### 5. Monitor Deployment

After applying, services will start deploying. Check status:

```bash
railway service list
# or
terraform output
```

## Outputs

After successful deployment, Terraform provides:

```bash
terraform output
```

Key outputs:
- `api_public_url` - Public endpoint for the chat API
- `grafana_url` - Grafana dashboard (login required)
- `api_private_url` - Internal endpoint
- `postgres_connection` - Database connection info
- `redis_connection` - Cache connection info

## Managing Infrastructure

### Update Variables

To change configuration (e.g., API replicas, memory limits):

```bash
# Edit terraform.tfvars
vim terraform.tfvars

# Plan the changes
terraform plan -out=tfplan

# Apply
terraform apply tfplan
```

### Destroy Infrastructure

⚠️ **WARNING**: This deletes all services and volumes. Only do this if you want to remove the entire stack.

```bash
terraform destroy
```

You'll be prompted to confirm. Type `yes` to proceed.

### Import Existing Resources

If you have an existing Railway project/services, you can import them:

```bash
terraform import railway_project.mpd <project_id>
terraform import railway_service.api <service_id>
# etc.
```

## Troubleshooting

### Authentication Error

```
Error: Unauthorized
```

**Solution**: Ensure `RAILWAY_TOKEN` is set and valid:
```bash
export RAILWAY_TOKEN="your_token"
echo $RAILWAY_TOKEN
```

### Service Deployment Fails

Check logs:
```bash
railway logs --service api
```

Common issues:
- Missing `services/__init__.py` - Run: `touch services/__init__.py && git add services/__init__.py && git commit`
- Missing dependencies - Check `pyproject.toml` has `psycopg`
- Database connection - Verify PostgreSQL is online and password is correct

### Resource Already Exists

If you get "resource already exists" error:

```bash
terraform state rm railway_service.api
terraform import railway_service.api <service_id>
```

## Best Practices

1. **Version Control**: Commit `terraform.tfvars.example`, NOT `terraform.tfvars`
2. **Secrets**: Use `-auto-approve=false` to always review changes
3. **State File**: Keep `terraform.tfstate` secure (it contains secrets)
4. **Backups**: Tag production deployments before major changes
5. **Cost Monitoring**: Check Railway dashboard for unexpected usage

## Advanced: Blue-Green Deployment

To set up blue-green deployment:

1. Create a second environment (e.g., "staging")
2. Deploy to staging first
3. Test thoroughly
4. Swap public domain from production to staging

Example:
```bash
terraform workspace new staging
terraform apply
# Test staging environment
terraform workspace select production
# Update outputs to use staging API
```

## Cost Estimation

Estimated monthly costs (from `deploy/railway/topology.yaml`):
- **Infrastructure**: ~$89/month
- **Variable**: Tokens per turn (~$30-180/month depending on usage)

To adjust resources, update `memory_mb` and `cpu_cores` in `services.tf`.

## Related Files

- `../railway/topology.yaml` - Source of truth for resource specs
- `../railway/api.toml` - API service build/deploy config
- `../../pyproject.toml` - Python dependencies
- `../../migrations/` - Database migrations (run via `preDeployCommand`)

## Support

For issues with:
- **Railway**: https://railway.app/docs
- **Terraform Railway Provider**: https://github.com/railwayapp/terraform-provider-railway
- **This project**: Check `docs/ARCHITECTURE.md` and `docs/runbooks/`
