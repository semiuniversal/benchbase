# vNext checklist

Legend: `[ ]` pending · `[~]` in progress · `[x]` done

**Architecture:** cross-phase choices live in [decisions/](decisions/README.md). Update an ADR (or supersede) before changing cohort rules, evidence layout, feature flags, or adapter boundaries.

## Release invariants (§14.1)

- [~] Historical SQLite + artifacts survive upgrade/rollback
- [x] No in-place rewrite of historic scores (policy + tests)
- [x] Unsafe generated code disabled by default (`coding_execution_enabled`)
- [x] OpenCode-only creative harness (mock + driver stub; Pi/OMP execution UI gated)
- [x] Tokens ≠ chunks; missing metrics ≠ zero (Arena)

## WP0 — Baseline

- [x] `scripts/vnext_backup.py` consistent SQLite backup
- [x] `scripts/vnext_inventory.py` schema + corpus hashes
- [x] `tests/test_vnext_backup.py`, `tests/test_vnext_wp0_restore.py`
- [x] Doc hub under `doc/vnext/` (+ [TESTING.md](TESTING.md))
- [ ] Owner: disposable restore on production backup archive (manual)

## WP1 — Comparison correctness

- [x] Default cohort `standard_completed`; smoke excluded from Borda pool
- [x] `compatibility_class` on dimensions
- [x] CSV `ranking_cohort`, `cohort_eligible`
- [x] API + MCP `ranking_cohort` query param
- [ ] Owner: Compare UI sanity — smoke-only seat vs standard rank

## WP2 — Measurement fixes

- [x] Arena provider usage + chunk rate provenance
- [x] `tests/test_arena_metrics.py`
- [ ] Owner: Arena stream sanity on one live model (usage vs chunk fallback)

## WP3 — Evidence and identity

- [x] `DeploymentRevision`, `EvidenceObservation`, `EvaluatorResult` models
- [x] Checkpoint → `record_item_evidence` + `/api/evidence/*`
- [x] `tests/test_vnext_evidence.py`, `tests/test_vnext_wp3_checkpoint_evidence.py`
- [ ] Full request/response capture in manifests (future tranche)
- [ ] Alembic revisions before non-additive schema ([alembic.md](alembic.md))

## WP5a — Heatmap

- [x] Heatmap tab on Compare

## WP5b — Inspector + Arena sessions

- [x] Run log filter (modal + API `q`)
- [x] Arena Save session + `/api/arena/sessions`
- [x] Live ETA: model×suite historical priors + running avg × remaining items (`run_timing_stats`)

## WP5c — Per-axis launch and rerun

- [x] API: `DELETE /runs/{id}?axis_only=true`, `POST /runs/{id}/rerun`, `POST /axis/start`
- [x] UI: single-axis launch; **Rerun benchmark** dialog (full tier + per-phase scores)
- [ ] UI: axis-only discard (delete one spoke without whole tier) — use rerun or axis_only delete via API
- See [plans/WP5c-axis-rerun.md](plans/WP5c-axis-rerun.md)

## UX — Retire Agentic Finalist (ADR-010)

- [x] Remove Benchmarks **Agentic Finalist** tab and launch UI
- [x] Remove Models finalist shortcuts; Creative Arena is the interactive track
- [~] Keep `agentic_omp_enabled` + legacy runs read-only until code archived

## WP4 — Empirical diagnostics

- [x] `scripts/vnext_diagnostics.py` → `doc/vnext/reports/` (+ `tests/test_vnext_wp4_diagnostics.py`)
- [~] Owner: run against production DB **copy**; review `diagnostics-latest.json` before scorer changes (snapshot on `docker/data` 2026-11-21)

## WP6 — Adapters

- [x] `src/benchbase/adapters/base.py` contract + stub registry + `GET /api/adapters/`

## WP7 — Creative foundation

- [~] `src/benchbase/creative/` workspace + event stream + mock runner (OpenCode pin TBD)
- [x] ZooCode→OpenCode skills + tool map: [creative-opencode-tools.md](creative-opencode-tools.md)
- [x] OMP runner disabled unless legacy flag

## WP8 — Creative Arena product

- [~] `volcano-skunk-v1` fixture
- [~] Creative Arena routes + UI (feature-flagged)
- [~] Read-only source viewer API

## WP9 — Integration and sharing

- [~] Provider-neutral settings aliases
- [~] Export/import package API + redaction
- [~] Self-host notes in `doc/vnext/SELF_HOST.md`