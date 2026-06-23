# PrimeNet production image (Linux containers)
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NCM_CONTAINER=1 \
    NCM_DATA_ROOT=/data \
    NCM_BOOTSTRAP_ON_IMPORT=0 \
    NCM_DISABLE_SCHEDULER=1 \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=8000

WORKDIR /app

# lxml runtime libs; build tools only if a wheel is unavailable
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin primenet \
    && mkdir -p /data/databases /data/sync_downloads /data/raw/KPIs \
    && chown -R primenet:primenet /app /data \
    && chmod +x /app/deploy/entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"

USER root
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["web"]
