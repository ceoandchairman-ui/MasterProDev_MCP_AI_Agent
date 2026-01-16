# ============================================================================
# COMPREHENSIVE MERGED DOCKERFILE - All Services in One Build
# ============================================================================
# Builds and orchestrates all 9 services (mcp-host, calendar, gmail, etc.)
# Individual Dockerfiles preserved for future strategy flexibility
# ============================================================================

FROM python:3.11-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libpq-dev \
    postgresql-client \
    redis-tools \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ============================================================================
# STAGE 1: Build ROOT DEPENDENCIES (mcp_host)
# ============================================================================

FROM base as mcp-host-builder

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_host/ /mcp_host/
COPY mcp_host/prompts.yaml /
COPY mcp_host/aliases.yaml /

# ============================================================================
# STAGE 2: Build CALENDAR SERVICE DEPENDENCIES
# ============================================================================

FROM base as calendar-builder

COPY mcp_servers/calendar_server/requirements.txt /calendar_requirements.txt
RUN pip install --no-cache-dir -r /calendar_requirements.txt

COPY mcp_servers/calendar_server/ /calendar_server/

# ============================================================================
# STAGE 3: Build GMAIL SERVICE DEPENDENCIES
# ============================================================================

FROM base as gmail-builder

COPY mcp_servers/gmail_server/requirements.txt /gmail_requirements.txt
RUN pip install --no-cache-dir -r /gmail_requirements.txt

COPY mcp_servers/gmail_server/ /gmail_server/

# ============================================================================
# FINAL STAGE: Combined Runtime Environment
# ============================================================================

FROM docker:24-dind

# Install all runtime dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    docker-compose \
    postgresql-client \
    redis \
    curl \
    ca-certificates \
    bash

WORKDIR /app

# Copy Python packages and source code from build stages
COPY --from=mcp-host-builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=mcp-host-builder /usr/local/bin /usr/local/bin
COPY --from=calendar-builder /calendar_server /app/mcp_servers/calendar_server
COPY --from=gmail-builder /gmail_server /app/mcp_servers/gmail_server

# Copy entire project structure
COPY . /app/

# Verify critical files exist
RUN test -f /app/docker-compose.yml || (echo "❌ docker-compose.yml not found" && exit 1)
RUN test -d /app/mcp_host || (echo "❌ mcp_host directory not found" && exit 1)
RUN test -d /app/mcp_servers/calendar_server || (echo "❌ calendar_server not found" && exit 1)
RUN test -d /app/mcp_servers/gmail_server || (echo "❌ gmail_server not found" && exit 1)

# Make entrypoint executable
RUN chmod +x /app/docker-entrypoint.sh

# Create directories for data persistence
RUN mkdir -p /app/postgres_data /app/redis_data /app/logs

# Expose all service ports
EXPOSE 8000 5432 6379 8080 8001 8002 9090 3000

# Health check for main service
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/docs || exit 1

# Use entrypoint script for proper initialization
ENTRYPOINT ["/app/docker-entrypoint.sh"]

# ============================================================================
# DOCKERFILE METADATA
# ============================================================================
LABEL version="1.0"
LABEL description="Merged Docker image: mcp-host, calendar_server, gmail_server + full stack"
LABEL maintainer="AI Agent MCP"
