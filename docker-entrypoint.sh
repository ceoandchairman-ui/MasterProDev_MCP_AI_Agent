#!/bin/bash
set -e

echo "🚀 Starting AI Agent MCP Services..."

cd /app
mkdir -p /app/logs

# Set Python path for all services - CRITICAL for module imports
export PYTHONPATH=/app

# Default environment variables if not set (Railway provides these)
# DATABASE_URL and REDIS_URL must be provided by the platform (no defaults with credentials)
: "${DATABASE_URL:?DATABASE_URL is required}"
: "${REDIS_URL:?REDIS_URL is required}"
# Shared secret between the host and the in-container tool servers; generated if not provided
export MCP_SERVICE_KEY="${MCP_SERVICE_KEY:-$(python -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export HUGGINGFACE_API_KEY="${HUGGINGFACE_API_KEY:-}"
if [ -z "$HUGGINGFACE_API_KEY" ]; then
  echo "⚠️  WARNING: HUGGINGFACE_API_KEY not set - LLM calls will fail"
fi

# Wait for Weaviate to be available (separate Railway service)
if [ -n "$WEAVIATE_HOST" ]; then
  # Removed blocking wait loop to allow "Fail Soft" startup
  # Python app will handle connection asynchronously in background
  
  # Run seeder to populate Weaviate (attempt only if ready, or skip - ideally should be async too)
  # For now, we skip blocking seeding to ensure fast startup. 
  # Seeding should be a separate job or triggered manually if Weaviate isn't ready instantly.
  if [ -d "/app/Company_Documents" ] && [ "$(ls -A /app/Company_Documents)" ]; then
    echo "📚 Running seeder in background (non-blocking)..."
    python /app/seed.py 2>&1 | tee -a /app/logs/seeder.log &
    SEEDER_PID=$!
    echo "   Seeder PID: $SEEDER_PID"
  else
    echo "⚠️  No Company_Documents found - skipping seeding"
  fi
fi

echo "📱 Starting mcp_host on port 8000 (with uvicorn)..."
python -m uvicorn mcp_host.main:app --host 0.0.0.0 --port 8000 2>&1 | tee -a /app/logs/mcp_host.log &
MCPHOST_PID=$!
echo "   PID: $MCPHOST_PID"

echo "�📅 Starting calendar_server on port 8001..."
python -m uvicorn mcp_servers.calendar_server.main:app --host 0.0.0.0 --port 8001 2>&1 | tee -a /app/logs/calendar_server.log &
CALENDAR_PID=$!
echo "   PID: $CALENDAR_PID"

echo "📧 Starting gmail_server on port 8002..."
python -m uvicorn mcp_servers.gmail_server.main:app --host 0.0.0.0 --port 8002 2>&1 | tee -a /app/logs/gmail_server.log &
GMAIL_PID=$!
echo "   PID: $GMAIL_PID"

echo "✅ All services started. Monitoring..."
echo ""
echo "Service Logs:"
echo "  - mcp_host:        /app/logs/mcp_host.log"
echo "  - calendar_server: /app/logs/calendar_server.log"
echo "  - gmail_server:    /app/logs/gmail_server.log"
echo ""

# Keep entrypoint running and restart any failed services
# Wait a bit before checking so services have time to start
sleep 5
echo ""
echo "Service Status:"
tail -20 /app/logs/mcp_host.log 2>/dev/null | head -10
echo ""

while true; do
  sleep 10
  
  # Check if services are still running, restart if needed
  if ! kill -0 $MCPHOST_PID 2>/dev/null; then
    echo "⚠️  mcp_host crashed, restarting..."
    python -m uvicorn mcp_host.main:app --host 0.0.0.0 --port 8000 2>&1 | tee -a /app/logs/mcp_host.log &
    MCPHOST_PID=$!
  fi
  
  if ! kill -0 $CALENDAR_PID 2>/dev/null; then
    echo "⚠️  calendar_server crashed, restarting..."
    python -m uvicorn mcp_servers.calendar_server.main:app --host 0.0.0.0 --port 8001 2>&1 | tee -a /app/logs/calendar_server.log &
    CALENDAR_PID=$!
  fi
  
  if ! kill -0 $GMAIL_PID 2>/dev/null; then
    echo "⚠️  gmail_server crashed, restarting..."
    python -m uvicorn mcp_servers.gmail_server.main:app --host 0.0.0.0 --port 8002 2>&1 | tee -a /app/logs/gmail_server.log &
    GMAIL_PID=$!
  fi
done
