# BenchBase MCP integration

Agents and MCP clients talk to the same FastAPI process as the web UI. Tools call the same services and SQLite store as `/api/*` — they do not HTTP-loop back to REST.

Implementation: [`src/benchbase/mcp_server.py`](../src/benchbase/mcp_server.py) (official **mcp v2** `MCPServer`). Radar shaping: [`src/benchbase/radar.py`](../src/benchbase/radar.py).

## Endpoints

| Path | Transport | Who uses it |
|------|-----------|-------------|
| **`/mcp`** | Streamable HTTP, **dual-era** | Cursor and other Streamable HTTP clients. Serves pre–2026-07-28 session/`initialize` **and** post–2026-07-28 stateless POSTs on one URL. |
| **`/sse`** | Legacy HTTP+SSE | Pre-Streamable clients. Message POST: `/sse/message`. |
| **`/api/*`** | REST | UI and scripts. Source of truth for behavior. |

Do not invent `/mcp/streamable`. The public URL is always `/mcp`.

Both `/mcp` and `/mcp/` are accepted (Starlette mounts otherwise only match the trailing slash).

## URLs

CLI `uv run benchbase serve` listens on **8000** by default. Docker compose publishes **`BENCHBASE_PORT` (default 8099)** → container 8000.

| How you run BenchBase | MCP URL |
|------------------------|---------|
| `uv run benchbase serve` | `http://127.0.0.1:8000/mcp` |
| Docker / Portainer (this host’s default) | `http://127.0.0.1:8099/mcp` |
| Another machine on the LAN | `http://<host>:<port>/mcp` |

Confirm with `uv run benchbase status` or `docker compose ps`. The UI and MCP share that port.

## Cursor

User or project MCP config (`~/.cursor/mcp.json` or `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "benchbase": {
      "url": "http://127.0.0.1:8099/mcp"
    }
  }
}
```

Use `8000` instead of `8099` if you are on the CLI server. Restart Cursor (or reload MCP) after editing. BenchBase must already be running.

Cursor lists the server as **user-benchbase** (user config) or **benchbase** (project config). No API token is required (LAN trust, same as the dashboard).

## Protocol notes

- **Dual-era:** session clients send `initialize` and may get `Mcp-Session-Id`. Stateless 2026-07-28 clients send per-request `MCP-Protocol-Version` / `Mcp-Method` / `Mcp-Name` and skip `initialize`. Both hit `/mcp`.
- **Application state is not in the MCP session.** Runs, models, and settings live in SQLite. Always pass `run_id`, `run_group_id`, `model_id`, `suite_id`, or `item_id` as tool arguments.
- **No live SSE tools.** Run-log SSE, arena SSE, and agentic event SSE are UI-only. Agents poll status/history tools. Streamable HTTP may still use `text/event-stream` for a single `tools/call` response — that is not a substitute for BenchBase’s long-lived log stream.
- **Host lifespan** must run `mcp.session_manager.run()` (wired in [`src/benchbase/main.py`](../src/benchbase/main.py)). A mounted sub-app’s own lifespan never starts.

## How agents should watch benchmarks

1. `get_batch_status` — `idle` / `running` / `paused` / `pausing`, `pending_count`, `model_concurrency`, `current_runs[]` (label, run_id, model, optional `timing`).
2. `list_active_runs` — every `pending` / `running` / `pausing` / `paused` row with suite, group, tier.
3. `get_run_timing` / `get_run_log_history` — progress and logs for a known `run_id`.

Poll on the order of tens of seconds. Do not open `/api/benchmarks/runs/{id}/log` from MCP.

## Tool catalog

### Status (poll these)

| Tool | Arguments | Purpose |
|------|-----------|---------|
| `get_batch_status` | — | Live queue + current runs + timing |
| `list_active_runs` | — | Pending / running / pausing / paused |
| `get_run` | `run_id` | One run + result summaries |
| `get_run_timing` | `run_id` | Elapsed, ETA, progress |
| `get_run_log_history` | `run_id` | Persisted log lines |

### Benchmarks

| Tool | Arguments | Purpose |
|------|-----------|---------|
| `start_batch` | `model_id`, `tier` (`smoke`\|`standard`\|`thorough`), `smoke_override?` | Queue a full tier |
| `cancel_batch` | — | Abort/discard the active tier set |
| `create_run` | `model_id`, `suite_id`, `eval_mode?` | Queue one suite (does not start) |
| `list_runs` | `model_id?`, `limit?` | Recent runs |
| `start_run` | `run_id` | Start a pending run |
| `pause_run` / `resume_run` | `run_id` | Cooperative pause; checkpoints kept |
| `pause_run_group` / `resume_run_group` | `run_group_id` | Pause/resume a tier set |
| `abort_run_group` | `run_group_id` | Stop and discard the set |
| `estimate_duration` | `suite_id`, `eval_mode?` | Rough duration preview |
| `list_suites` | — | Registered suites |
| `run_controls` | `tier?` | Null/random/echo scorers |
| `controls_status` | — | Scorer validity |
| `start_agentic` | `model_id`, `suite_version?`, `n_seeds?`, `mock?`, `instrument_validation?` | Finalist · Agentic (sole tenancy) |

### Models

| Tool | Arguments | Purpose |
|------|-----------|---------|
| `list_models` | — | Registry |
| `get_model` | `model_id` | Detail + recent runs |
| `add_model` | `name`, `endpoint_url`, optional runtime/quant/`host` | Register |
| `update_model` | `model_id` + optional color, notes, context, VRAM, status, `base_model`, `quant_rank` | Metadata |
| `archive_model` / `unarchive_model` | `model_id` | Hide/restore on Compare |
| `bulk_archive` | `model_ids` | Archive many |
| `delete_model` | `model_id` | Delete model and runs |
| `discover_models` | — | Upsert from LiteLLM |
| `recheck_models` | — | Health check |
| `list_model_runs` | `model_id`, `limit?` | Runs for one model |
| `list_finalist_eligible` | — | Standard/Thorough complete |

### Settings

| Tool | Arguments | Purpose |
|------|-----------|---------|
| `get_settings` | — | Public settings (`litellm_api_key_set`, never the key) |
| `update_settings` | optional URL, key, theme, sample limits, concurrency, work-clock reference, timeout | Persist YAML |
| `probe_litellm` | `model?` | Detect sticky `min_tokens` |

### Results / Compare

| Tool | Arguments | Purpose |
|------|-----------|---------|
| `get_model_scorecard` | — | Ranked six-axis scorecard, pass/fail gates, and speed |
| `get_scorecard` | `run_ids` | Scorecard for specific runs |
| `compare_runs` | `run_ids` | Per-task scores |
| `get_results_by_run` | `run_id` | Task results |
| `get_radar_chart_data` | optional `model_names`, `stretch`, `group_by_family`, `active_only`, `show_smoke`, `show_unbenchmarked` | Plot-ready radar |

Radar JSON (mirrors Compare page):

- `axis_keys` — `knowledge`, `reasoning`, `math`, `coding`, `tool_calling`, `instruction` (structured and long context stay on the scorecard as pass/fail gates, not spokes)
- `axes[]` — `key`, `label`, `scores[model_name]` with `value`, `raw`, `ci_low`, `ci_high`, `n_items`, `planned_n`, `rank`
- `series[]` — model name, color, overall rank, Borda
- `radar_data[]` — Recharts-style rows (`axis`, `_axisKey`, per-model values)

### Arena

| Tool | Arguments | Purpose |
|------|-----------|---------|
| `arena_chat` | `prompt`, `models`, `max_tokens?`, `temperature?` | Same prompt to many models (JSON, not SSE) |

### Agentic inspect

| Tool | Arguments | Purpose |
|------|-----------|---------|
| `get_agentic_current` | `run_id` | Current attempt pointer |
| `list_agentic_attempts` | `run_id` | Attempts for a run |
| `get_agentic_transcript` | `run_id`, `item_id` (`task:seedN`) | Normalized transcript |
| `get_agentic_workspace` | `run_id`, `item_id` | Fixture tree |
| `get_agentic_workspace_file` | `run_id`, `item_id`, `path` | One fixture file |

### Not exposed

`stream_run_log`, `arena_stream`, `stream_agentic_attempt_events`. Bulk wipe (`delete_all_runs`) is also not an MCP tool.

Errors from REST (`HTTPException`) come back as `{ "error": true, "status_code": N, "detail": "..." }` rather than a protocol-level failure.

## Smoke test

With BenchBase up:

```bash
curl -sS -X POST http://127.0.0.1:8099/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
```

Expect **200** and SSE `data:` with `serverInfo.name` = `BenchBase`. Capture `mcp-session-id`, then `tools/list` and `tools/call` `get_batch_status`. Idle queue looks like `{"status":"idle","pending_count":0}`.

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| `404 {"detail":"Not Found"}` on `/mcp` | Old image without the slash-free rewrite, or SPA catching the path. Rebuild/redeploy. Confirm POST `/mcp` (no trailing slash) returns 200. |
| `RuntimeError: Task group is not initialized` | Host lifespan is not entering `mcp.session_manager.run()`. |
| `421 Misdirected Request` | DNS-rebinding allowlist (localhost-only). BenchBase serves with `host=0.0.0.0` so LAN Host headers are accepted. |
| Cursor shows the server but tools fail | BenchBase stopped or wrong port (8000 vs 8099). |
| Stale OpenAPI-style tool names (`get_benchmark_batch_status`) | Client still on pre-mcp-v2 `fastapi-mcp`. Reload MCP; image must include `mcp>=2`. |

## Related

- README MCP section (short pointer)
- [`docker/README.md`](../docker/README.md) — compose port and `/sse`
- [MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [mcp Python SDK — mount under FastAPI](https://py.sdk.modelcontextprotocol.io/v2/run/asgi/)
