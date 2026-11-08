FROM python:3.11-slim

WORKDIR /app

COPY services/mcp_calendar/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/__init__.py ./services/__init__.py
COPY services/_common ./services/_common
COPY services/mcp_calendar ./services/mcp_calendar

ENV PYTHONPATH=/app
RUN useradd --create-home app
USER app
EXPOSE 8001
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"
CMD ["python", "-m", "uvicorn", "--factory", "services.mcp_calendar.main:create", "--host", "0.0.0.0", "--port", "8001"]
