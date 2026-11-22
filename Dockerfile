# BabelGrade — web front + in-process job workers (one container).
# The async job queue (Whisper / OCR / AI analysis) runs as asyncio tasks inside
# the uvicorn process (see docs/async-jobs.md), so there is no separate worker.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    BABELGRADE_DB_PATH=/app/data/babelgrade.db \
    BABELGRADE_WHISPER_CACHE=/app/data/hf-cache

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY static ./static
COPY docs ./docs
COPY run.sh ./run.sh

RUN useradd --create-home --uid 1000 babelgrade \
    && mkdir -p /app/data/uploads /app/data/hf-cache \
    && chown -R babelgrade:babelgrade /app
USER babelgrade

EXPOSE 8090
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8090/api/health', timeout=4).status==200 else 1)"

CMD ["./run.sh"]
