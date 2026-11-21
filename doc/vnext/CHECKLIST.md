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

- [~] `scripts/vnext_backup.py` consistent SQLite backup
- [~] `scripts/vnext_inventory.py` schema + corpus hashes
- [~] `tests/test_vnext_backup.py` disposable restore
- [x] Doc hub under `doc/vnext/`

## WP1 — Comparison correctness

- [~] Default cohort `standard_completed`; smoke excluded from Borda pool
- [~] `compatibility_class` on dimensions
- [~] CSV `ranking_cohort`, `cohort_eligible`
- [~] API `ranking_cohort` query param

## WP2 — Measurement fixes

- [~] Arena provider usage + chunk rate provenance
- [~] `tests/test_arena_metrics.py`

## WP3 — Evidence and identity

- [~] `DeploymentRevision`, `EvidenceObservation` models
- [~] `benchbase/evidence/store.py` artifact paths
- [~] `tests/test_vnext_evidence.py`

## WP4 — Empirical diagnostics

- [~] `scripts/vnext_diagnostics.py` → `doc/vnext/reports/`

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