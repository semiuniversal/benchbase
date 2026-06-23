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

### MCP (Model Context Protocol)

BenchBase exposes its REST API as MCP tools over **Streamable HTTP** at the same server:

- **URL:** `http://localhost:8000/mcp` (use `uv run benchbase status` if you are not on the default port)
- **Tools:** ~26 operations (benchmark runs, models, results, settings, arena chat) with OpenAPI-derived schemas and descriptions
- **Excluded:** SSE-only endpoints (`stream_run_log`, `arena_stream`); use `get_benchmark_run_log_history` and `arena_chat` instead

**Cursor** — add to your MCP config (project or user):

```json
{
  "mcpServers": {
    "benchbase": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Restart Cursor after changing MCP settings. Ensure BenchBase is running (`uv run benchbase serve`) before the agent connects.

### Docker

Production deployment uses the files in [`docker/`](docker/). **Full Portainer instructions:** [`docker/README.md`](docker/README.md).

```bash
cd docker
cp .env.example .env   # set absolute paths for BENCHBASE_HOST_DATA and BENCHBASE_HOST_CONFIG
mkdir -p ./data        # or your configured data path
docker compose up --build -d
```

The app is available at **http://localhost:8000** (MCP at `/mcp`).

**Data persistence:** Bind-mount `docker/data` → `/app/data` holds `benchbase.db`, WAL files, and `run_logs/`. Bind-mount `config/` → `/app/config` for `settings.yaml`. The database is **not** in the image. If you previously used CLI dev mode, migrate `benchbase.db` from the repo root into `docker/data/` before first container start (see docker README).

**LiteLLM from Docker:** Use `http://host.docker.internal:4000` (or your host IP) in Settings — not `localhost`.

Do not run `benchbase serve` on the host and Docker against the same data directory at the same time.

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
