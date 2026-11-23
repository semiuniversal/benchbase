# Self-hosting BenchBase (vNext)

1. Copy `config/settings.yaml.example` → `config/settings.yaml`.
2. Set OpenAI-compatible `litellm_base_url` / `inference_base_url` (same field; WP9 alias).
3. `docker compose -f docker/docker-compose.yml up --build` (data in `docker/data/`).
4. Run `uv run python scripts/vnext_backup.py` before upgrades.
5. **Alembic:** after backup, `uv run alembic -c alembic.ini stamp head` (see [alembic.md](alembic.md)).
6. Creative Arena: enable `creative_arena_enabled` after WP7 review; optional worker:
   `docker compose -f docker/docker-compose.worker.yml up -d` (internal network only).
7. OpenCode live: set `BENCHBASE_OPENCODE_LIVE=1` on worker only after pinned short test.
8. Export/import: `POST /api/export/evaluation-evidence`, `/challenge`, `/creative-artifact`; import with `dry_run` or `persist:true` (stored under `docker/data/imports/`, inert until applied).
9. Capabilities discovery: `GET /api/capabilities/deployments?ranking_cohort=standard_completed`.
10. Mock demo: use synthetic scorecards only; redact endpoints in shared exports.

## Migrations

- Greenfield: `init_db()` on app startup creates schema.
- Upgrades: additive columns via `init_db()` until Alembic revision applies DDL; never wipe production SQLite without owner backup.

## Creative isolation

- Generated code runs in worker workspace volumes, not on the API container.
- Preview serves static files from frozen workspace (`/api/creative/attempts/{uuid}/preview`).