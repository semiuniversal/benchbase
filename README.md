# BenchBase

Local LLM Benchmark Dashboard — a single web-based evaluation surface for locally hosted LLMs exposed through OpenAI-compatible endpoints (e.g. LiteLLM).

## What It Does

BenchBase provides one dashboard covering four evaluation dimensions:

- **Speed** — latency, time to first token, generation throughput
- **Coding** — HumanEval-style code generation benchmarks
- **Tool Use** — instruction following and tool-call correctness
- **Reasoning** — GSM8K, MMLU, and similar benchmark families

It also includes an **Arena mode** for sending the same prompt to multiple models simultaneously with real-time streaming metrics.

## Tech Stack

| Layer    | Technology                           |
|----------|--------------------------------------|
| Backend  | Python 3.11+, FastAPI, SQLAlchemy    |
| Frontend | TypeScript, React, Mantine UI        |
| Database | SQLite (default), Postgres-ready     |
| Packaging| UV (Python), npm (Node)              |
| Deploy   | Docker / docker-compose              |

## Quick Start

### Development (without Docker)

```bash
uv sync
uv run benchbase serve --reload
```

This builds the frontend, initializes the database, and starts the API server on `http://localhost:8000`.

For frontend-only development, run `npm run dev` in `frontend/` — it proxies `/api` requests to the backend at `localhost:8000`.

### Docker

```bash
cd docker
docker compose up --build
```

The app is available at `http://localhost:8000`.

## Configuration

Edit `config/settings.yaml` to set your LiteLLM proxy URL, default models, enabled benchmark suites, and theme preference. Settings are also editable from the web UI's Settings page.

## Project Structure

```
benchbase/
  src/benchbase/     Python FastAPI backend
  frontend/          React/Mantine frontend
  docker/            Dockerfile and docker-compose
  config/            Default settings.yaml
  doc/               Product documentation
  pyproject.toml     UV-managed dependencies
```
