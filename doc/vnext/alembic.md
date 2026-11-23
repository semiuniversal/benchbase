# Alembic (planned, ADR-004)

vNext tables (`deployment_revisions`, `evidence_observations`, `evaluator_results`, …) are created via `init_db()` → `create_all` on startup.

Before any **non-additive** migration (column drops, data backfill), add Alembic revisions here and document upgrade steps in this file. Do not wipe production runs.

## Bootstrap (2026-11-23)

1. `uv run alembic -c alembic.ini stamp head` on a DB already at `init_db()` schema (after `scripts/vnext_backup.py`).
2. New installs: `init_db()` on startup remains authoritative until a revision applies real DDL.

Initial revision: `20261123_0001` (no-op stamp).