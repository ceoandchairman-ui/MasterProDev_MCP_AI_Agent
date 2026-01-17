#!/bin/sh

# Start dockerd in background
echo "🐳 Starting Docker daemon..."
dockerd-entrypoint.sh &
DOCKERD_PID=$!

echo "⏳ Waiting for Docker daemon to be ready..."
MAX_ATTEMPTS=60
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
  if [ -S /var/run/docker.sock ] && docker ps >/dev/null 2>&1; then
    echo "✓ Docker daemon is ready"
    break
  fi
  ATTEMPT=$((ATTEMPT + 1))
  echo "⏳ Waiting... ($ATTEMPT/$MAX_ATTEMPTS)"
  sleep 1
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
  echo "❌ Docker daemon failed to start after $MAX_ATTEMPTS seconds"
  kill $DOCKERD_PID 2>/dev/null || true
  exit 1
fi

echo "🚀 Starting docker-compose services..."
cd /app
exec docker-compose up
