# ADR-010: Retire Agentic Finalist benchmark UI; Creative Arena is the interactive track

**Status:** accepted  
**Date:** 2026-11-22  
**Work packages:** WP5 (UX), WP7–WP8 (Creative)

## Context

Early **Agentic Finalist** (OMP/Bun, `/benchmarks?tab=finalist`, `agentic` runner) was an attempt at an interactive coding benchmark. vNext spec §11 places subjective, open-ended app building in **Creative Arena** with **OpenCode** only—not Pi/OMP/ZooCode as product surfaces.

Tier batches (`start_batch`) never included the `agentic` axis; the finalist tab is a parallel product path that confuses operators and duplicates intent.

## Decision

- **Remove from product UI (next application pass):** Benchmarks **Agentic Finalist** tab, finalist launch controls, Models-page finalist shortcuts, and primary navigation to agentic inspect flows.
- **Keep behind flags / read-only until removal is safe:** `agentic_omp_enabled` (ADR-005), historic `agentic:*` runs in SQLite for inspection/export; no new dependence on OMP mounts for operators.
- **Replace operator workflow:** Creative Arena for open-ended builds; tier benchmarks remain **Smoke → Standard/Thorough** axes only.

## Consequences

- One less harness story to maintain in the main UX.
- Agentic runner code can be deleted or archived in a later bounded PR after data retention policy is confirmed.
- Compare/radar do not incorporate agentic scores today; removal does not change Borda cohorts.

## Follow-up tasks

1. Drop finalist tab from `BenchmarksPage.tsx`; remove `InspectSessionModal` entry points from primary flows (optional deep link for legacy runs during transition).
2. Remove Models finalist CTA; point “creative” workflows to Creative Arena when enabled.
3. Hide `agentic` suite from “launchable” lists; document legacy runs in operator docs.
4. Trim docker OMP/Bun mounts from default compose when no code path requires them (`agentic_omp_enabled=false`).