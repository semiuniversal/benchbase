# ADR-009: Export redacts secrets; import stays inert by default

**Status:** accepted  
**Date:** 2026-11-21  
**Work packages:** WP9

## Context

Spec §13.1: portable packages must not leak keys, hostnames, or raw conversations by default.

## Decision

- **`POST /api/export/evaluation-evidence`** builds `benchbase.export.v1` with regex redaction on scorecards ([`export_pkg.py`](../../../src/benchbase/api/routes/export_pkg.py)).
- **`POST /api/export/import`** validates schema; **`dry_run=true` default**; persistence returns 501 until explicit design for imported identity (spec: never masquerade as local verified runs).
- Capability summary API is read-only at **`/api/capabilities/deployments`**.

## Consequences

- Sharing workflow is safe-by-default; full lossless export remains an explicit future option with user confirmation.
- Gallery/creative artifact export reuses same redaction patterns when added (reference this ADR).