# ADR-001: Default ranking cohort is completed standard or thorough

**Status:** accepted  
**Date:** 2026-11-21  
**Work packages:** WP1

## Context

The methodology audit showed smoke-only deployments could top the **global** Borda pool while Compare UI only hid smoke optionally. Spec §9.1 requires the ranking cohort to be defined before scoring and used consistently in UI and CSV.

## Decision

- Introduce `ranking_cohort` on scorecard computation (`standard_completed` default, `all_eligible` for legacy parity).
- A model is **cohort-eligible** for Borda only when `best_tier` is `standard` or `thorough`.
- Axis ranks and overall Borda are computed **only among cohort-eligible** models for `standard_completed`.
- Per-dimension `compatibility_class` labels legacy version mismatch and incomplete sittings without rewriting scores.

Implementation: [`scoring_cohort.py`](../../../src/benchbase/scoring_cohort.py), [`scoring.py`](../../../src/benchbase/scoring.py), API `GET /api/results/model-scorecard?ranking_cohort=…`.

## Consequences

- Smoke-only models keep displayed scores but lose default overall rank (expected).
- CSV gains `ranking_cohort` and `cohort_eligible` columns aligned with API.
- MCP/radar consumers must pass cohort explicitly if they need legacy pool behavior (`all_eligible`).