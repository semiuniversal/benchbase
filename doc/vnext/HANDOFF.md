# BenchBase vNext — implementation handoff

**Date:** 2026-11-22  
**Authority:** [BenchBase vNext Specification v1.2](../BenchBase_vNext_Specification_v1.2.md)  
**Living progress:** [CHECKLIST.md](CHECKLIST.md) · **ADRs:** [decisions/](decisions/README.md)  
**Git:** `main` (ahead of `origin/main`; many vNext commits local)

This document is for the owner and the next agent (or a follow-on spec) to resume work without re-deriving state from chat logs.

---

## 1. What BenchBase is today

BenchBase is a **local-model evaluation laboratory**: FastAPI + SQLite + React/Mantine UI, usually deployed via **`benchbase:local`** on **port 8099** (`docker/docker-compose.yml`). Inference goes through an OpenAI-compatible gateway (`config/settings.yaml` → `litellm_base_url` / LLManifold in practice).

| Mode (spec §1) | Purpose | Current maturity |
|----------------|---------|-------------------|
| **Benchmarks** | Quantitative tier runs (Smoke / Standard / Thorough) | **Production-ready core**; queue, pause/resume, per-axis rerun, progress UI |
| **Compare** | Cohort-aware scorecards, heatmap, work clock, gates | **Usable**; known Speed display gap (below) |
| **Arena** | Side-by-side chat + usage semantics (WP2) | **Usable**; owner sanity on live streams still open |
| **Creative Arena** | OpenCode-oriented challenge + gallery (WP7–8) | **Feature-flagged** (`creative_arena_enabled`); mock harness + UI, not full isolated worker |

Legacy **Agentic Finalist (OMP/Pi)** is **retired in UI** ([ADR-010](decisions/ADR-010-retire-agentic-finalist-ui.md)); backend flag `agentic_omp_enabled` remains for historical runs.

---

## 2. Position vs specification v1.2

The spec (§14) defines work packages **WP0–WP9** with release invariants (§14.1). Implementation is **partial**: strong progress on comparison cohorts, measurement fixes, UX, Creative foundation, and benchmarks ops; **weak** on full evidence capture, Alembic, production creative isolation, adapters in use, and **operator-facing Speed decode clarity**.

### Work package summary

| Package | Spec §14 gate (abridged) | Status | Notes |
|---------|--------------------------|--------|-------|
| **WP0** Baseline | Backup/restore, inventory, no prod data loss | **Mostly done** | Scripts + tests; owner disposable restore on prod backup still manual |
| **WP1** Comparison | Cohort-aware ranks; smoke excluded from standard pool | **Done in code** | Default `ranking_cohort=standard_completed`; compare UI smoke sanity owner task |
| **WP2** Measurement | Arena tokens ≠ chunks; speed gate reasons preserved | **Mostly done** | Synthetic tests; live Arena stream check open |
| **WP3** Evidence | Revisions, full obs, rescore linkage, migrations | **Partial** | Models + checkpoint evidence API; no full Alembic; truncated legacy `raw_answer` |
| **WP4** Diagnostics | Read-only BFCL/coding/TPS reports before scorer changes | **Partial** | `scripts/vnext_diagnostics.py` + tests; run on prod DB **copy** before changing scorers |
| **WP5** UX | Heatmap, inspector, sessions, dense compare | **Partial** | Heatmap, filtered log, Arena sessions, **rerun dialog**, **progress bars**, active-time ETA |
| **WP6** Adapters | Optional upstream evaluators, pinned | **Stub only** | Registry + API; no Lighthouse-style adapters wired |
| **WP7** Creative foundation | Isolated worker, OpenCode pin | **Early** | Mock runner, skills map, workspace SSE; **not** production sandbox for generated code |
| **WP8** Creative product | Volcano, gallery, source viewer, previews | **Early** | UI + API behind flag; Kasm/liminal preview not finished |
| **WP9** Sharing | Provider-neutral, export/import, self-host | **Early** | Partial settings aliases, export redaction ADR; LLManifold-neutral discovery incomplete |

Legend matches [CHECKLIST.md](CHECKLIST.md): treat unchecked owner lines as **human verification**, not missing code.

### Release invariants (§14.1) — spot check

| # | Invariant | State |
|---|-----------|--------|
| 1 | Historic SQLite + artifacts survive upgrade | **Policy + backup scripts**; Alembic not yet canonical |
| 2 | Scores show method/cohort; comparable populations | **WP1**; CSV/UI cohort params |
| 3 | Tokens ≠ chunks; missing ≠ zero | **WP2** Arena; Speed **gated null** still confuses Compare |
| 4 | ~1h standard target; partial ≠ complete tier | **Enforced in UX** (paused/orphan batch); tier can stall on one axis |
| 5 | Live observation retained | **Yes** (log modal, monitor, Arena) |
| 6 | OpenCode only creative harness | **Yes** (OMP UI retired) |
| 7–10 | Creative attempt integrity, isolation, sharing | **Not fully met** — see WP7–9 |

---

## 3. Architecture (as built)

```
Mantine UI → FastAPI (src/benchbase/api)
          → batch_scheduler + run_executor → runners (litebench, speed/llama-benchy, coding, …)
          → SQLite (runs, results, result_items) + run logs on disk
          → scoring / work_clock → Compare, Models, export
```

**Key modules** (audit index still largely valid): `scoring.py`, `scoring_cohort.py`, `work_clock.py`, `speed_gate.py`, `batch_scheduler.py`, `run_timing.py`, `run_timing_stats.py`, `creative/`, `adapters/`.

**Persistence:** `init_db()` + additive alters in `db/session.py` ([ADR-004](decisions/ADR-004-schema-init-db-then-alembic.md)). WP3 tables exist (`DeploymentRevision`, evidence observations) but **full capture** is not default on every item.

---

## 4. Benchmarks operator picture

### Tier execution

- **Order:** Smoke → … → Speed (10 axes) per `batch_scheduler._TIER_AXIS_ORDER`.
- **Concurrency:** `batch_model_concurrency` in settings (e.g. 2).
- **Serial within tier:** Lower `run.id` axes must finish before later axes for same `run_group_id` (except known historical anomalies — investigate if violated).
- **Pause/resume:** Cooperative; checkpoints on quality axes (e.g. Coding `ResultItem` rows).
- **Interrupt/restart:** Worker marks run **paused**; `active_ms` accumulates work time; batch status **rehydrates paused groups from DB** after container restart (recent fix).

### Rerun (WP5c)

- **API:** `POST /runs/{id}/rerun`, `POST /axis/start`, `DELETE /runs/{id}?axis_only=true`.
- **UI:** Recycle icon → dialog: **entire tier** or **per-phase** rerun (clears scores, full rescore — **not** checkpoint resume).
- **Caution:** “Rerun entire tier” replays all axes including Speed (llama-benchy); easy to misuse while Coding is paused.

### Progress & ETA

- **`GET /runs/{id}/timing`:** Progress %, **active** elapsed (not wall clock since `started_at`), ETA from item latencies / history.
- **UI:** `RunProgressPanel` in log modal and batch banner.

### Settings (`config/settings.yaml`)

| Setting | Typical role |
|---------|----------------|
| `coding_execution_enabled` | **Must be true** for real LiveCodeBench scores (was false during early Inkling standard) |
| `creative_arena_enabled` | Creative routes/UI |
| `agentic_omp_enabled` | Legacy OMP (keep false) |
| `work_clock_reference_model` | Compare speed **index** baseline (configurable seat name; not hardcoded in UI copy) |

**LiteLLM hygiene:** After Speed `--exact-tg`, restart LiteLLM or probe — sticky `min_tokens` breaks quality routes (workspace rule).

---

## 5. Compare & Speed — critical product gap

**User expectation:** “Tokens per second” on Compare.

**Implementation today:**

- Compare **tok/s column** = gated metric **`speed:output_tps2048`** only (`scoring._extract_speed` skips `score is None`).
- **Speed runner:** llama-benchy `tg=2048`, `--exact-tg`, **replicate gate** ([`speed_gate.py`](../src/benchbase/speed_gate.py)): ≥2/3 replicates with visible tokens ≥ 0.95×2048.
- **Thinking routes** often emit **~150–250 visible tokens** → gate stores **`invalid_reason: short EOS`** → Compare shows **—**.
- **`-nothink` Spark seats** often **pass** (e.g. `glm-5.3-flash-spark` ~38 tok/s).

**Still stored when gated:** prefill tps, TTFT, think ms, completion ms, token counts, work clock (sec/correct). Spec §2 / §9.1 intentionally **do not** invent comparable headline decode tok/s.

**Gap for next spec:** Define an **honest, user-visible decode throughput** (ungated observed visible tok/s, shorter `tg` profile, or nothink-only speed seat) **without** breaking §14.1 invariant #3. Owner has indicated a **focused follow-on spec** on this topic.

See also: [speed-index-requirements.md](../speed-index-requirements.md), `doc/speed-index-requirements.md` (work clock vs decode).

---

## 6. Creative Arena (WP7–8 snapshot)

- **Flag:** `creative_arena_enabled`.
- **Delivered:** Challenges API, attempts + SSE events, file tree + read-only source, gallery list, model picker (active seats only), volcano fixture path, OpenCode **skill stubs** ([creative-opencode-tools.md](creative-opencode-tools.md)).
- **Not delivered:** Pinned OpenCode worker in isolated container, durable artifact gallery at spec §11 depth, preview isolation (Kasm/liminal), subjective rating persistence at scale.

---

## 7. Evidence, diagnostics, export

- **WP3:** `record_item_evidence` on checkpoints; `/api/evidence/*` — incremental, not full request/response on all legacy suites.
- **WP4:** `scripts/vnext_diagnostics.py` → `doc/vnext/reports/diagnostics-latest.json` (often pytest fixture path unless owner runs against prod copy).
- **WP9:** `POST /api/export/evaluation-evidence` with redaction ([ADR-009](decisions/ADR-009-export-redaction-default.md)); capabilities JSON at `/api/capabilities/deployments`.

---

## 8. Tests & quality

```bash
uv run pytest          # ~164+ tests at last full run
cd frontend && npm run build
```

Docker image bundles frontend build. **Do not** run long tier benchmarks in CI without owner approval.

---

## 9. Live fleet context (2026-11-22, revenant)

Illustrative **owner session** (not invariant):

- **Inkling** (`inkling-2-mini-q3-prism`): Standard tier group `tier-74269a85782a`, **9/10 axes completed**, **Coding #1593 paused** (~26/40 checkpoint items when last inspected) — **Resume**, not full-tier rerun, to finish.
- **Speed** on Inkling: **output_tps2048 null** (short EOS gate); strong prefill/think metrics only.
- **`main` unpushed:** large local commit stack; treat repo as source of truth over this handoff if they diverge.

---

## 10. Planned but not implemented (from discussion)

**Role-based model recommendations** (gates + Pareto + optional LLM narrator on frozen scorecard) — discussed; **no code**. Spec §9.1 warns against universal weighted scores; prefer versioned **role catalog** if built.

---

## 11. Safe constraints for the next agent

1. **No** historic score rewrites; **no** production DB wipe without owner.
2. **No** sticky `min_tokens` in LiteLLM config; Speed uses request-scoped exact-tg.
3. **No** full Docker rebuild during long benchmarks unless owner asks.
4. **Commit:** workspace auto-commit on delivery; owner may prefer explicit commit for docs-only — follow user git rule when in conflict.
5. **Mesh:** revenant; mail via mesh-relay MCP when tools available.

---

## 12. Suggested reading order

1. [CHECKLIST.md](CHECKLIST.md)  
2. [RECONCILIATION.md](RECONCILIATION.md) (baseline facts; update when schema shifts)  
3. Spec §1, §9.1 (compare/speed), §11 (Creative), §14  
4. [ADR-001](decisions/ADR-001-ranking-cohorts.md), [ADR-010](decisions/ADR-010-retire-agentic-finalist-ui.md), [plans/WP5c-axis-rerun.md](plans/WP5c-axis-rerun.md)  
5. Methodology audit + response under `doc/BenchBase_Cursor_Methodology_Audit*.md`

---

## 13. Handoff to a “Speed / decode tok/s” mini-spec

**Starting facts for that doc:**

- Current primary metric is **gated** `speed:output_tps2048`.
- Compare UX treats missing as empty; users read as “no benchmark.”
- Work clock and think latency are **separate** product surfaces today.
- Fleet split: **nothink** seats populate tok/s; **thinking** seats often do not.
- Options space: secondary column, tooltip with `invalid_reason`, nothink speed profile, shorter `tg`, litellm route policy, ADR amending §14.1 #3 only with explicit “estimated” semantics.

**End of handoff.**