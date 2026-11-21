# WP1 — Comparison correctness

**Branch:** `feat/vnext/wp1-cohorts`  
**Depends on:** WP0

**ADR:** [ADR-001](../decisions/ADR-001-ranking-cohorts.md)

## Touch list

- `src/benchbase/scoring.py` — cohort filter, compatibility_class
- `src/benchbase/api/routes/results.py` — `ranking_cohort` query
- `frontend` — Compare cohort badge, CSV columns
- `tests/test_vnext_cohorts.py`

## Acceptance

- Smoke-only models excluded from default standard Borda pool
- CSV cohort fields match API
- Historic score values unchanged