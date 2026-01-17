# ============================================================================
# MERGED DOCKERFILE - All Services in Single Container (No Docker-in-Docker)
# ============================================================================
# Multi-stage build: Each service built separately, all run as Python processes
# Individual Dockerfiles preserved for future flexibility
# ============================================================================

FROM python:3.11-slim as base

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make libpq-dev postgresql-client redis-tools curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ============================================================================
# STAGE 1: mcp_host builder
# ============================================================================

FROM base as mcp-host-builder

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_host/ /mcp_host/
COPY prompts.yaml /prompts.yaml
COPY mcp_host/aliases.yaml /aliases.yaml

# ============================================================================
# STAGE 2: calendar_server builder
# ============================================================================

FROM base as calendar-builder

COPY mcp_servers/calendar_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_servers/calendar_server/ /calendar_server/

# ============================================================================
# STAGE 3: gmail_server builder
# ============================================================================

FROM base as gmail-builder

COPY mcp_servers/gmail_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_servers/gmail_server/ /gmail_server/

# ============================================================================
# FINAL STAGE: Python Runtime (No Docker-in-Docker)
# ============================================================================

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make libpq-dev postgresql-client redis-tools curl ca-certificates bash supervisor \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from ALL builders (critical: must merge all dependencies)
COPY --from=mcp-host-builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=calendar-builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=gmail-builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=mcp-host-builder /usr/local/bin /usr/local/bin

# Copy service code
COPY --from=mcp-host-builder /mcp_host /app/mcp_host
COPY --from=mcp-host-builder /prompts.yaml /app/prompts.yaml
COPY --from=mcp-host-builder /aliases.yaml /app/mcp_host/aliases.yaml
COPY --from=calendar-builder /calendar_server /app/mcp_servers/calendar_server
COPY --from=gmail-builder /gmail_server /app/mcp_servers/gmail_server

# Copy entire project
COPY . /app/

# Copy and make executable the entrypoint script (has monitoring/restart logic)
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Expose service ports (mcp-host, calendar, gmail, weaviate)
EXPOSE 8000 8001 8002 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/docs || exit 1

# Start all services
CMD ["/app/docker-entrypoint.sh"]
