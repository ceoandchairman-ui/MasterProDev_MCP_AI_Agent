FROM python:3.11-slim

WORKDIR /app

COPY services/mcp_db/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/_common ./services/_common
COPY services/mcp_db ./services/mcp_db

ENV PYTHONPATH=/app
RUN useradd --create-home app
USER app
EXPOSE 8004
CMD ["python", "-m", "uvicorn", "--factory", "services.mcp_db.main:create", "--host", "0.0.0.0", "--port", "8004"]
