#!/bin/bash
set -e

echo "🚀 Starting AI Agent MCP Services..."

cd /app
mkdir -p /app/logs

# Set Python path for all services - CRITICAL for module imports
export PYTHONPATH=/app

# Default environment variables if not set (Railway provides these)
export DATABASE_URL="${DATABASE_URL:-postgresql://mcpagent:mcpagent_dev_password@postgres:5432/mcpagent}"
export REDIS_URL="${REDIS_URL:-redis://:mcpagent_dev_password@redis:6379/0}"
export WEAVIATE_URL="${WEAVIATE_URL:-http://weaviate:8080}"
export HUGGINGFACE_API_KEY="${HUGGINGFACE_API_KEY:-}"

echo "📱 Starting mcp_host on port 8000 (with uvicorn)..."
python -m uvicorn mcp_host.main:app --host 0.0.0.0 --port 8000 2>&1 | tee -a /app/logs/mcp_host.log &
MCPHOST_PID=$!
echo "   PID: $MCPHOST_PID"

echo "📅 Starting calendar_server on port 8001..."
cd /app/mcp_servers/calendar_server && python main.py 2>&1 | tee -a /app/logs/calendar_server.log &
CALENDAR_PID=$!
echo "   PID: $CALENDAR_PID"

echo "📧 Starting gmail_server on port 8002..."
cd /app/mcp_servers/gmail_server && python main.py 2>&1 | tee -a /app/logs/gmail_server.log &
GMAIL_PID=$!
echo "   PID: $GMAIL_PID"

echo "✅ All services started. Monitoring..."
echo ""
echo "Service Logs:"
echo "  - mcp_host:      /app/logs/mcp_host.log"
echo "  - calendar_server: /app/logs/calendar_server.log"
echo "  - gmail_server:  /app/logs/gmail_server.log"
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
    cd /app/mcp_servers/calendar_server && python main.py 2>&1 | tee -a /app/logs/calendar_server.log &
    CALENDAR_PID=$!
  fi
  
  if ! kill -0 $GMAIL_PID 2>/dev/null; then
    echo "⚠️  gmail_server crashed, restarting..."
    cd /app/mcp_servers/gmail_server && python main.py 2>&1 | tee -a /app/logs/gmail_server.log &
    GMAIL_PID=$!
  fi
done
