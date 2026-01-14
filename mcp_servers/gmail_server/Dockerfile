FROM python:3.11-slim

WORKDIR /app

# Copy all server code to make Python imports work
COPY mcp_servers/ ./mcp_servers

# Install build-essential for compiling packages
RUN apt-get update && apt-get install -y build-essential

# Install dependencies for this specific server
COPY mcp_servers/gmail_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set the PYTHONPATH to the app root
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
    CMD python -c "import requests; requests.get('http://localhost:8002/health')"

# Run the specific server's main module
CMD ["python", "-m", "uvicorn", "mcp_servers.gmail_server.main:app", "--host", "0.0.0.0", "--port", "8002"]
