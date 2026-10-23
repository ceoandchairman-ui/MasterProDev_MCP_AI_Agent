FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

# tesseract is used only when OCR_ENGINE=tesseract; the eng and fra packs cover the supported languages
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[ocr]"

# The documents the reindex job reads (KNOWLEDGE_BASE_PATH)
COPY Company_Documents ./Company_Documents

RUN useradd --system --uid 10001 appuser
USER appuser

CMD ["python", "-m", "mpd_assistant.worker.main"]
