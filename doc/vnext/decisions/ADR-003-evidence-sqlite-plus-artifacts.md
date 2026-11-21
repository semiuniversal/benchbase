# ADR-003: Evidence = indexed SQLite rows + filesystem artifacts

**Status:** accepted  
**Date:** 2026-11-21  
**Work packages:** WP3

## Context

Spec §4.2 requires append-only observations with large payloads off-database. Current `ResultItem.raw_answer` is truncated and not rescore-friendly.

## Decision

- **`EvidenceObservation`** table stores manifest path, content hash, schema version, links to `run_id` / `deployment_revision_id`.
- **`write_observation_manifest()`** writes under `{DATA_DIR}/artifacts/observations/{run_id}/{item_id}/` ([`evidence/store.py`](../../../src/benchbase/evidence/store.py)).
- Derived scores remain in existing `Result` / `ResultItem`; new full evidence is additive. Rescoring appends evaluator results without overwriting manifests (WP3 follow-up).

## Consequences

- Docker bind-mount `data/` must include `artifacts/` in backups ([`scripts/vnext_backup.py`](../../../scripts/vnext_backup.py) tar path).
- Runners adopt the store incrementally; no big-bang migration of historic rows.