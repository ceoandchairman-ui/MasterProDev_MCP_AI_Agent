FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY mcp_host/ mcp_host/

# Expose port
EXPOSE 8000

# Start the FastAPI application
CMD ["uvicorn", "mcp_host.main:app", "--host", "0.0.0.0", "--port", "8000"]
