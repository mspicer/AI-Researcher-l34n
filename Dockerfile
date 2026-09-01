# syntax=docker/dockerfile:1
# Dashboard + hourly ingest in one process. SQLite lives in /data.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    AIR_HOST=0.0.0.0 \
    AIR_PORT=8899 \
    AIR_DATA_DIR=/data \
    AIR_AUTO_REFRESH_MIN=60

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

# Hatchling needs the README/LICENSE next to pyproject at build time.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir -e . \
    && chown -R app:app /app

USER app

EXPOSE 8899

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('AIR_PORT', '8899'), timeout=4)"

ENTRYPOINT ["ai-researcher"]
CMD ["serve"]
