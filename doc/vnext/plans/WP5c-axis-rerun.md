# WP5c — Per-axis benchmark launch, discard, and rerun

**Depends on:** WP5b (inspector / run log)  
**Blocks:** Honest operator control (e.g. rerun Coding after enabling `coding_execution_enabled`)

## Problem (verified 2026-11-22)

- UI and API only expose **`POST /api/benchmarks/batch/start`** — one **tier** (all axes in `_TIER_AXIS_ORDER`).
- **`DELETE /api/benchmarks/runs/{id}`** on a member of a `run_group_id` **deletes the entire tier set**, not one axis.
- **`POST /api/benchmarks/runs/{id}/resume`** only continues a **paused** run and **skips already-scored items** — not a full discard/rerun.
- “Available Suites” table is **read-only**; no per-suite launch.

Operators cannot drop LiveCodeBench (or any single axis) and rerun it without replaying the full tier or hand-editing the database.

## Target UX

1. **Tier runs** table: expand a group → one row per axis (suite) with score, gate reason, duration.
2. Per axis actions (when group not running on that axis):
   - **Rerun** — delete this axis’s results/run (only this member), create a new `Run` in the **same `run_group_id`** and tier, enqueue.
   - **Discard** — delete axis run/results without immediate rerun (group may be incomplete until user reruns or runs full tier).
3. **Launch** panel: optional mode **“Single axis”** — pick model + tier + suite → queue one run (solo `run_group_id` or attach to latest open group — **default: new solo group** unless user picks “attach to tier set X”).
4. Surface **infrastructure / gate** reasons in axis row (e.g. `coding_execution_disabled`) with link to Settings when applicable.

## API (proposed)

| Method | Path | Behavior |
|--------|------|----------|
| `POST` | `/api/benchmarks/axis/start` | `{ model_id, suite_id, tier, smoke_override?, run_group_id? }` → create `Run`, enqueue |
| `POST` | `/api/benchmarks/runs/{id}/rerun` | Abort if running; delete results for that run only; reset status pending; enqueue (full rescore, no skip) |
| `DELETE` | `/api/benchmarks/runs/{id}/axis-only` | Delete **one** run in a group; **recompute** group batch job `run_ids` if active; refuse if that axis is running |

Change `DELETE /runs/{id}` semantics or add axis-only route — **do not** silently delete whole tier when user intended one axis (breaking change; document in release notes).

## Backend notes

- `batch_scheduler` queue must tolerate **missing members** in a group (pending list shrinks) and **appended** reruns (optional: max one run per suite_id per group).
- Compare/scorecard: latest **completed** run per `(model, suite, tier)` or explicit **run_group** — confirm WP1 cohort rules when group is partially rerun.
- Tests: axis-only delete preserves sibling runs; rerun clears `result_items`; smoke gate still applies for standard/thorough single-axis launch.

## Acceptance

- From UI, after enabling `coding_execution_enabled`, operator can **rerun Coding only** for inkling (or any model) without replaying BFCL.
- Deleting one axis does not wipe sibling axes in the same tier set.
- Agentic finalist tab removed per ADR-010 (separate PR).