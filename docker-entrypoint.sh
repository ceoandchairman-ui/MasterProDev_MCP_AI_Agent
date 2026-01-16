#!/bin/sh
set -e

echo "🐳 Initializing Docker-in-Docker..."

# Wait for dockerd to be fully ready
MAX_ATTEMPTS=30
ATTEMPT=0
while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
  if dockerd-entrypoint.sh &>/dev/null || [ -S /var/run/docker.sock ]; then
    echo "✓ Docker daemon ready"
    break
  fi
  ATTEMPT=$((ATTEMPT + 1))
  echo "⏳ Waiting for Docker daemon... ($ATTEMPT/$MAX_ATTEMPTS)"
  sleep 1
done

# Ensure docker socket exists and is accessible
if [ ! -S /var/run/docker.sock ]; then
  echo "❌ Docker socket not found at /var/run/docker.sock"
  exit 1
fi

# Test docker connection
echo "🧪 Testing Docker connection..."
if ! docker ps >/dev/null 2>&1; then
  echo "❌ Docker connection failed"
  exit 1
fi
echo "✓ Docker connection successful"

# Start docker-compose services
echo "🚀 Starting docker-compose services..."
cd /app
docker-compose up

# Keep the container running
tail -f /dev/null
