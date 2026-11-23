# vNext checklist

Legend: `[ ]` pending · `[~]` in progress · `[x]` done

**Architecture:** cross-phase choices live in [decisions/](decisions/README.md). Update an ADR (or supersede) before changing cohort rules, evidence layout, feature flags, or adapter boundaries.

## Release invariants (§14.1)

- [x] Historical SQLite + artifacts survive upgrade/rollback (Alembic stamp + `init_db()` path)
- [x] No in-place rewrite of historic scores (policy + tests)
- [x] Unsafe generated code disabled by default (`coding_execution_enabled`)
- [x] OpenCode-only creative harness (mock + driver stub; Pi/OMP execution UI gated)
- [x] Tokens ≠ chunks; missing metrics ≠ zero (Arena)

## WP0 — Baseline

- [x] `scripts/vnext_backup.py` consistent SQLite backup
- [x] `scripts/vnext_inventory.py` schema + corpus hashes
- [x] `tests/test_vnext_backup.py`, `tests/test_vnext_wp0_restore.py`
- [x] Doc hub under `doc/vnext/` (+ [TESTING.md](TESTING.md))
- [x] Owner: disposable restore on production backup archive (2026-11-23 `/tmp/benchbase-wp4`)

## WP1 — Comparison correctness

- [x] Default cohort `standard_completed`; smoke excluded from Borda pool
- [x] `compatibility_class` on dimensions
- [x] CSV `ranking_cohort`, `cohort_eligible`
- [x] API + MCP `ranking_cohort` query param
- [ ] Owner: Compare UI sanity — smoke-only seat vs standard rank

## WP2 — Measurement fixes

- [x] Arena provider usage + chunk rate provenance
- [x] `tests/test_arena_metrics.py`
- [x] Addendum A: `decode-4k-512-c1-v1` profile, `speed:decode_tps*`, UI/export (`tests/test_decode_tps.py`)
- [x] Speed route procedure + `verify-speed-routes` / Speed preflight ([SPEED_DECODE_ROUTE_PROCEDURE.md](SPEED_DECODE_ROUTE_PROCEDURE.md))
- [ ] Owner: Arena stream sanity on one live model (usage vs chunk fallback)

## WP3 — Evidence and identity

- [x] `DeploymentRevision`, `EvidenceObservation`, `EvaluatorResult` models
- [x] Checkpoint → `record_item_evidence` + `/api/evidence/*`
- [x] `tests/test_vnext_evidence.py`, `tests/test_vnext_wp3_checkpoint_evidence.py`
- [x] LLM request/response summary in evidence manifests (`llm_evidence` on new checkpoints)
- [x] Alembic baseline stamp ([alembic.md](alembic.md) · `20261123_0001`)

## WP5a — Heatmap

- [x] Heatmap tab on Compare

## WP5b — Inspector + Arena sessions

- [x] Run log filter (modal + API `q`)
- [x] Arena Save session + `/api/arena/sessions`
- [x] Live ETA: model×suite historical priors + running avg × remaining items (`run_timing_stats`)

## WP5c — Per-axis launch and rerun

- [x] API: `DELETE /runs/{id}?axis_only=true`, `POST /runs/{id}/rerun`, `POST /axis/start`
- [x] UI: single-axis launch; **Rerun benchmark** dialog (full tier + per-phase scores)
- [x] UI: axis-only discard in Rerun benchmark dialog (`deleteRun` axis_only)
- See [plans/WP5c-axis-rerun.md](plans/WP5c-axis-rerun.md)

## UX — Retire Agentic Finalist (ADR-010)

- [x] Remove Benchmarks **Agentic Finalist** tab and launch UI
- [x] Remove Models finalist shortcuts; Creative Arena is the interactive track
- [~] Keep `agentic_omp_enabled` + legacy runs read-only until code archived

## WP4 — Empirical diagnostics

- [x] `scripts/vnext_diagnostics.py` → `doc/vnext/reports/` (+ `tests/test_vnext_wp4_diagnostics.py`)
- [x] Owner: diagnostics on prod backup copy (`doc/vnext/reports/diagnostics-latest.json` 2026-11-23)

## WP6 — Adapters

- [x] `src/benchbase/adapters/base.py` contract + stub registry + `GET /api/adapters/`
- [x] `tinybenchmarks` offline adapter + golden fixture (`tests/test_vnext_adapter.py`)
- [x] `decode-32k-512-c1-v1` speed profile + `decode_tps_32k` scorecard field

## WP7 — Creative foundation

- [x] `opencode_driver` mock default; pin `1.0.80`; worker compose isolation stub
- [x] ZooCode→OpenCode skills + tool map: [creative-opencode-tools.md](creative-opencode-tools.md)
- [x] OMP runner disabled unless legacy flag

## WP8 — Creative Arena product

- [x] `volcano-skunk-v1` fixture
- [x] Creative Arena routes + UI (feature-flagged)
- [x] Read-only source viewer API + static preview routes
- [x] PATCH rating/notes persistence API
- [ ] Owner: isolated preview sandbox (Kasm/liminal) — static preview only until chosen

## WP9 — Integration and sharing

- [x] Provider-neutral settings aliases (`inference_base_url`)
- [x] Export: evaluation, challenge, creative-artifact; import persist (inert)
- [x] Capabilities API v2 axis breakdown
- [x] [SELF_HOST.md](SELF_HOST.md) expanded