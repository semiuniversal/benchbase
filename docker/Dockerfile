# ---- Stage 1: Build frontend ----
FROM node:22-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev

COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Default config baked in; production stacks should bind-mount host config/.
COPY config/ ./config/

ENV BENCHBASE_DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/settings/ || exit 1

# Frontend is pre-built in the image; skip CLI rebuild and dev reload.
CMD ["uv", "run", "benchbase", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-reload", "--skip-build"]
