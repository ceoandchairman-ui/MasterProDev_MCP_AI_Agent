FROM python:3.11-slim

WORKDIR /app

COPY services/mcp_quoting/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only the pure pricing code from the main package, so this image stays small
COPY src/mpd_assistant/__init__.py ./mpd_assistant/__init__.py
COPY src/mpd_assistant/business/__init__.py ./mpd_assistant/business/__init__.py
COPY src/mpd_assistant/business/quoting.py ./mpd_assistant/business/quoting.py
COPY src/mpd_assistant/business/catalog.py ./mpd_assistant/business/catalog.py
COPY services/_common ./services/_common
COPY services/mcp_quoting ./services/mcp_quoting

ENV PYTHONPATH=/app
RUN useradd --create-home app
USER app
EXPOSE 8003
CMD ["python", "-m", "uvicorn", "--factory", "services.mcp_quoting.main:create", "--host", "0.0.0.0", "--port", "8003"]
