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

# Copy installed packages from all builders
COPY --from=mcp-host-builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=mcp-host-builder /usr/local/bin /usr/local/bin

# Copy service code
COPY --from=mcp-host-builder /mcp_host /app/mcp_host
COPY --from=mcp-host-builder /prompts.yaml /app/prompts.yaml
COPY --from=mcp-host-builder /aliases.yaml /app/mcp_host/aliases.yaml
COPY --from=calendar-builder /calendar_server /app/mcp_servers/calendar_server
COPY --from=gmail-builder /gmail_server /app/mcp_servers/gmail_server

# Copy entire project
COPY . /app/

# Create startup script for all services
RUN cat > /app/start-services.sh << 'EOF'
#!/bin/bash
set -e

echo "🚀 Starting AI Agent MCP Services..."

# Start mcp_host (main FastAPI app)
echo "📱 Starting mcp_host..."
cd /app && python -m uvicorn mcp_host.main:app --host 0.0.0.0 --port 8000 &
MCP_HOST_PID=$!

# Start calendar_server
echo "📅 Starting calendar_server..."
cd /app/mcp_servers/calendar_server && python main.py &
CALENDAR_PID=$!

# Start gmail_server
echo "📧 Starting gmail_server..."
cd /app/mcp_servers/gmail_server && python main.py &
GMAIL_PID=$!

echo "✓ All services started"
echo "  - mcp_host (PID: $MCP_HOST_PID)"
echo "  - calendar_server (PID: $CALENDAR_PID)"
echo "  - gmail_server (PID: $GMAIL_PID)"

# Keep container running
wait $MCP_HOST_PID
EOF

RUN chmod +x /app/start-services.sh

# Expose service ports
EXPOSE 8000 8001 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/docs || exit 1

# Start all services
CMD ["/app/start-services.sh"]
