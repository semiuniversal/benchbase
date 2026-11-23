# BenchBase vNext — plan of plans

**Authority:** [BenchBase vNext Specification v1.2](../BenchBase_vNext_Specification_v1.2.md) · [Decode TPS Addendum A](../BenchBase_vNext_Addendum_Decode_TPS_v1.0.md)  
**Status:** implementation in progress  
**Git:** one feature branch per work package; merge to `main` when acceptance gates pass.

## Documents

| Document | Purpose |
|----------|---------|
| [HANDOFF.md](HANDOFF.md) | **Current implementation state vs spec v1.2** (agent/owner resume) |
| [CHECKLIST.md](CHECKLIST.md) | Living acceptance gates and progress |
| [TESTING.md](TESTING.md) | Phase delivery test protocol |
| [decisions/README.md](decisions/README.md) | **ADRs** — cross-phase architecture (read before contradicting) |
| [RECONCILIATION.md](RECONCILIATION.md) | Verified repo facts vs spec §2–§3 |
| [plans/WP0-baseline.md](plans/WP0-baseline.md) | Backup, inventory, migration smoke |
| [plans/WP1-comparison-correctness.md](plans/WP1-comparison-correctness.md) | Cohorts, Borda, CSV parity |
| [plans/WP2-measurement-fixes.md](plans/WP2-measurement-fixes.md) | Arena token semantics |
| [plans/WP3-evidence-identity.md](plans/WP3-evidence-identity.md) | Revisions, observations, artifacts |
| [plans/WP4-empirical-diagnostics.md](plans/WP4-empirical-diagnostics.md) | Read-only BFCL/coding reports |
| [plans/WP5a-heatmap-compare.md](plans/WP5a-heatmap-compare.md) | Heatmap tab |
| [plans/WP5b-live-inspector-arena.md](plans/WP5b-live-inspector-arena.md) | Inspector + Arena sessions |
| [plans/WP5c-axis-rerun.md](plans/WP5c-axis-rerun.md) | Single-axis launch, discard, rerun |
| [plans/WP6-evaluator-adapters.md](plans/WP6-evaluator-adapters.md) | Adapter framework |
| [plans/WP7-creative-execution-foundation.md](plans/WP7-creative-execution-foundation.md) | Worker, OpenCode, mock harness |
| [plans/WP8-creative-arena-product.md](plans/WP8-creative-arena-product.md) | Volcano challenge, gallery, source view |
| [plans/WP9-integration-sharing.md](plans/WP9-integration-sharing.md) | Provider-neutral, export/import |

## Branch policy

| Branch | Work package |
|--------|----------------|
| `feat/vnext/wp0-baseline` | WP0 (+ stacked delivery commits for WP1–WP9 until individual branches are split) |
| `feat/vnext/wp1-cohorts` | WP1 (optional split) |
| `feat/vnext/wp2-measurement` | WP2 |

Recommended order: WP0 → WP1 ∥ WP2 → WP4 → WP3 → WP5 → WP6 → WP7 → WP8 → WP9.

## Agent constraints

- No production inference or gateway config changes without owner approval.
- No in-place historic score rewrites.
- Feature-flag incomplete UI (`creative_arena_enabled` in settings).