# Alembic (planned, ADR-004)

vNext tables (`deployment_revisions`, `evidence_observations`, `evaluator_results`, …) are created via `init_db()` → `create_all` on startup.

Before any **non-additive** migration (column drops, data backfill), add Alembic revisions here and document upgrade steps in this file. Do not wipe production runs.