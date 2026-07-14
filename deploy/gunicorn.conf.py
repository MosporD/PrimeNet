"""Gunicorn configuration for production (container or bare-metal Linux)."""

import os

_reload = os.getenv("GUNICORN_RELOAD", "").lower() in ("1", "true", "yes")

bind = f"0.0.0.0:{os.getenv('FLASK_PORT', '8000')}"
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))
worker_class = "gthread"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "600"))
graceful_timeout = 30
keepalive = 5
preload_app = not _reload
reload = _reload
reload_extra_files = []
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
capture_output = True
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "0")) or 0
max_requests_jitter = 50 if max_requests else 0
