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

- [~] `DeploymentRevision`, `EvidenceObservation` models
- [~] `benchbase/evidence/store.py` artifact paths
- [~] `tests/test_vnext_evidence.py`

## WP4 — Empirical diagnostics

- [x] `scripts/vnext_diagnostics.py` → `doc/vnext/reports/` (+ `tests/test_vnext_wp4_diagnostics.py`)
- [ ] Owner: run against production DB **copy**; review `diagnostics-latest.json` before scorer changes

## WP5a — Heatmap

- [~] Heatmap tab on Compare (absolute / relative / delta)

## WP5b — Inspector + Arena sessions

- [~] `ArenaSession` persistence + API
- [~] Run log filter/search API params

## WP6 — Adapters

- [~] `src/benchbase/adapters/base.py` contract

## WP7 — Creative foundation

- [~] `src/benchbase/creative/` worker boundary + mock harness
- [~] OMP runner disabled unless legacy flag

## WP8 — Creative Arena product

- [~] `volcano-skunk-v1` fixture
- [~] Creative Arena routes + UI (feature-flagged)
- [~] Read-only source viewer API

## WP9 — Integration and sharing

- [~] Provider-neutral settings aliases
- [~] Export/import package API + redaction
- [~] Self-host notes in `doc/vnext/SELF_HOST.md`