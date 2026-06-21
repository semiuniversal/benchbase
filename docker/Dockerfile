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

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install backend dependencies
COPY backend/pyproject.toml backend/README.md ./backend/
COPY backend/src/ ./backend/src/
RUN cd backend && uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Copy config defaults
COPY config/ ./config/

# Runner dependencies directory
RUN mkdir -p /opt/runners

EXPOSE 8000

WORKDIR /app/backend
CMD ["uv", "run", "benchbase", "serve", "--host", "0.0.0.0", "--port", "8000"]
