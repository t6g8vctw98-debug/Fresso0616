# ─── Fresso backend — production image ──────────────────────────────────────
# Flask + gunicorn. Works on Railway, Render, Fly.io and any Docker host.

FROM python:3.11-slim

# Prevent Python from writing .pyc files & buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5001

WORKDIR /app

# System deps:
#  - build-essential / libxml2 / libxslt for lxml & bcrypt wheels fallback
#  - curl for the container HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libxml2-dev \
        libxslt1-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App code
COPY . .

# SQLite data lives here. On Railway/Render/Fly mount a persistent volume at
# /app/instance so the DB survives redeploys (see render.yaml / fly.toml).
RUN mkdir -p /app/instance

EXPOSE 5001

# Container-level health check hits the backend /health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/api/health" || exit 1

# Honour the platform-injected $PORT (Railway/Render set it dynamically);
# falls back to 5001 locally. 2 workers + 4 threads is a sane small default.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5001} --workers 2 --threads 4 --timeout 120 backend:app"]
