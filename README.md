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
uv run benchbase serve
```

This builds the frontend, initializes the database, and starts **one** server on **http://localhost:8000**. Always use that URL.

`benchbase serve` **replaces** any previous BenchBase process (even on another port) before starting. You should not run multiple copies or alternate ports during normal dev.

| Command | Purpose |
|---------|---------|
| `uv run benchbase serve` | Start (or restart) the server with auto-reload |
| `uv run benchbase serve --skip-build` | Restart after backend-only changes |
| `uv run benchbase status` | See if a server is running and which URL |
| `uv run benchbase stop` | Stop the server |

**Restarting:** Run `uv run benchbase serve` again — no manual `kill` needed.

**Stopping is not crashing:** Exit code **143** means the process was stopped (Ctrl+C or a new `serve` replaced it). That is normal.

**Where data lives (dev):** `benchbase.db` and `run_logs/` in the project root (see `config/settings.yaml`). Docker uses `docker/data/` instead.

For frontend-only development, run `npm run dev` in `frontend/` — it proxies `/api` to **http://localhost:8000**.

### Docker

```bash
cd docker
docker compose up --build
```

The app is available at `http://localhost:8000`.

**Data persistence:** SQLite (`benchbase.db`), run logs, and other runtime data are stored in `docker/data/` on the host (bind-mounted to `/app/data` in the container). They survive container restarts and image rebuilds. LiteLLM URL and API keys remain in `config/settings.yaml` (also mounted from the host). Local CLI development uses the project root (`benchbase.db`, `run_logs/`) unless you set `BENCHBASE_DATA_DIR` or `BENCHBASE_DB_URL`.

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
