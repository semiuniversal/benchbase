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

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

COPY --from=frontend-build /app/frontend/dist ./frontend/dist

COPY config/ ./config/

EXPOSE 8000

CMD ["uv", "run", "benchbase", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-reload"]
