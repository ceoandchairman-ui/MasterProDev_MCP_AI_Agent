#!/bin/bash
set -e

echo "🚀 Starting AI Agent MCP Services..."

cd /app
mkdir -p /app/logs

# Set Python path for all services - CRITICAL for module imports
export PYTHONPATH=/app

echo "📱 Starting mcp_host on port 8000..."
python /app/mcp_host/main.py > /app/logs/mcp_host.log 2>&1 &
MCPHOST_PID=$!
echo "   PID: $MCPHOST_PID"

echo "📅 Starting calendar_server on port 8001..."
python /app/mcp_servers/calendar_server/main.py > /app/logs/calendar_server.log 2>&1 &
CALENDAR_PID=$!
echo "   PID: $CALENDAR_PID"

echo "📧 Starting gmail_server on port 8002..."
python /app/mcp_servers/gmail_server/main.py > /app/logs/gmail_server.log 2>&1 &
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
while true; do
  sleep 10
  
  # Check if services are still running, restart if needed
  if ! kill -0 $MCPHOST_PID 2>/dev/null; then
    echo "⚠️  mcp_host crashed, restarting..."
    python /app/mcp_host/main.py > /app/logs/mcp_host.log 2>&1 &
    MCPHOST_PID=$!
  fi
  
  if ! kill -0 $CALENDAR_PID 2>/dev/null; then
    echo "⚠️  calendar_server crashed, restarting..."
    python /app/mcp_servers/calendar_server/main.py > /app/logs/calendar_server.log 2>&1 &
    CALENDAR_PID=$!
  fi
  
  if ! kill -0 $GMAIL_PID 2>/dev/null; then
    echo "⚠️  gmail_server crashed, restarting..."
    python /app/mcp_servers/gmail_server/main.py > /app/logs/gmail_server.log 2>&1 &
    GMAIL_PID=$!
  fi
done
