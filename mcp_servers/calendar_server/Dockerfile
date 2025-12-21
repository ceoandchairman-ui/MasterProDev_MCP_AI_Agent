FROM python:3.11-slim

WORKDIR /app

# Copy all server code to make Python imports work
COPY mcp_servers/ ./mcp_servers

# Install dependencies for this specific server
COPY mcp_servers/calendar_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set the PYTHONPATH to the app root
ENV PYTHONPATH=/app

# Run the specific server's main module
CMD ["python", "-m", "uvicorn", "mcp_servers.calendar_server.main:app", "--host", "0.0.0.0", "--port", "8001"]
