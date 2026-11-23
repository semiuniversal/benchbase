# BenchBase vNext — implementation handoff

**Date:** 2026-11-22 (updated after Decode Addendum + full-suite UX)  
**Authority:** [BenchBase vNext Specification v1.2](../BenchBase_vNext_Specification_v1.2.md) · [Addendum A: Decode TPS](../BenchBase_vNext_Addendum_Decode_TPS_v1.0.md)  
**Living progress:** [CHECKLIST.md](CHECKLIST.md) · **ADRs:** [decisions/](decisions/README.md)  
**Git:** `main` (ahead of `origin/main`; large local stack — verify with `git log` before trusting counts here)

This document is for the owner and the next agent (or a follow-on spec) to resume work without re-deriving state from chat logs.

---

## 1. What BenchBase is today

BenchBase is a **local-model evaluation laboratory**: FastAPI + SQLite + React/Mantine UI, usually deployed via **`benchbase:local`** on **port 8099** (`docker/docker-compose.yml`). Inference goes through an OpenAI-compatible gateway (`config/settings.yaml` → `litellm_base_url` / LLManifold in practice).

| Mode (spec §1) | Purpose | Current maturity |
|----------------|---------|-------------------|
| **Benchmarks** | Quantitative tier runs (Smoke / Standard / Thorough) | **Production-ready core**; queue, pause/resume, per-axis rerun, progress UI |
| **Compare** | Cohort-aware scorecards, heatmap, work clock, gates, **decode tok/s radar spoke** | **Usable**; legacy runs lack `decode-4k-512-c1-v1` until Speed re-run |
| **Arena** | Side-by-side chat + usage semantics (WP2) | **Usable**; owner sanity on live streams still open |
| **Creative Arena** | OpenCode-oriented challenge + gallery (WP7–8) | **Feature-flagged** (`creative_arena_enabled`); mock harness + UI, not full isolated worker |

Legacy **Agentic Finalist (OMP/Pi)** is **retired in UI** ([ADR-010](decisions/ADR-010-retire-agentic-finalist-ui.md)); backend flag `agentic_omp_enabled` remains for historical runs.

---

## 2. Position vs specification v1.2

The spec (§14) defines work packages **WP0–WP9** with release invariants (§14.1). Implementation is **partial**: strong progress on comparison cohorts, measurement fixes, UX (decode hero, full suite), Creative foundation, and benchmarks ops; **weak** on full evidence capture, Alembic, production creative isolation, adapters in use, and optional long-context speed profiles.

### Work package summary

| Package | Spec §14 gate (abridged) | Status | Notes |
|---------|--------------------------|--------|-------|
| **WP0** Baseline | Backup/restore, inventory, no prod data loss | **Mostly done** | Scripts + tests; owner disposable restore on prod backup still manual |
| **WP1** Comparison | Cohort-aware ranks; smoke excluded from standard pool | **Done in code** | Default `ranking_cohort=standard_completed`; compare UI smoke sanity owner task |
| **WP2** Measurement | Arena tokens ≠ chunks; speed gate reasons preserved | **Mostly done** | **Addendum A** `decode-4k-512-c1-v1`, `speed:decode_tps*`; Arena shows `—` tok/s without token timing; live Arena sanity still owner task |
| **WP3** Evidence | Revisions, full obs, rescore linkage, migrations | **Partial** | Models + checkpoint evidence API; no full Alembic; truncated legacy `raw_answer` |
| **WP4** Diagnostics | Read-only BFCL/coding/TPS reports before scorer changes | **Partial** | `scripts/vnext_diagnostics.py` + tests; run on prod DB **copy** before changing scorers |
| **WP5** UX | Heatmap, inspector, sessions, dense compare | **Partial** | Heatmap, filtered log, Arena sessions, rerun dialog, progress bars, **DecodeSpeedCard** (Models/Compare), **full suite** one-click queue |
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
| 3 | Tokens ≠ chunks; missing ≠ zero | **WP2** Arena; headline **decode_tps** null + reason on UI (legacy `output_tps2048` kept) |
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

**Key modules:** `scoring.py`, `decode_tps.py`, `speed_gate.py`, `batch_scheduler.py` (`start_full_suite`, smoke→standard follow-up), `run_timing*.py`, `runners/speed.py`, `runners/llama_benchy_results_patch.py`, `creative/`, `adapters/`.

**Frontend (speed UX):** `DecodeSpeedCard.tsx`, `SpeedPlate.tsx`, Compare radar spoke `decode_speed`, `export_scorecard_csv` decode columns.

**Persistence:** `init_db()` + additive alters in `db/session.py` ([ADR-004](decisions/ADR-004-schema-init-db-then-alembic.md)). WP3 tables exist (`DeploymentRevision`, evidence observations) but **full capture** is not default on every item.

---

## 4. Benchmarks operator picture

### Tier execution

- **Order:** Smoke → … → Speed (10 axes) per `batch_scheduler._TIER_AXIS_ORDER`.
- **Concurrency:** `batch_model_concurrency` in settings (e.g. 2).
- **Serial within tier:** Lower `run.id` axes must finish before later axes for same `run_group_id` (except known historical anomalies — investigate if violated).
- **Pause/resume:** Cooperative; checkpoints on quality axes (e.g. Coding `ResultItem` rows).
- **Interrupt/restart:** Worker marks run **paused**; `active_ms` accumulates work time; batch status **rehydrates paused groups from DB** after container restart (recent fix).

### Full suite (one button)

- **API:** `POST /benchmarks/batch/start-full-suite` → `start_full_suite()` in `batch_scheduler.py`.
- **Logic:** If Smoke **passed** → queue **Standard** (re-run OK). Else queue **Smoke** with `follow_up_tier=standard`; on Smoke batch **complete**, chain Standard **only if** `_has_passing_smoke`. In-flight Smoke can be tagged with follow-up via same endpoint.
- **UI:** Models **Full suite**; Benchmarks tier tab **Queue full suite** (manual tier picker remains).
- **Limitation:** Follow-up is in-memory + `follow_up_tier` on run `config_json`; after **worker restart mid-Smoke**, click Full suite again to re-attach Standard. Thorough is **not** auto-chained.

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

## 5. Decode tok/s (Addendum A — implemented 2026-11-22)

**Spec:** [BenchBase_vNext_Addendum_Decode_TPS_v1.0.md](../BenchBase_vNext_Addendum_Decode_TPS_v1.0.md) · commits `50bedd5`, `b76e019`.

### Canonical headline

| Item | Value |
|------|--------|
| Profile | `decode-4k-512-c1-v1` — pp **4096**, tg **512**, **5** measured reps (tier `passes` in suite config), concurrency 1 |
| DB row | `speed:decode_tps512` — **median** of valid replicates (≥3 of 5, ≥384 generated tokens) |
| Measurement | **Generated** tokens (reasoning + visible when streamed); `generated_decode_tg_throughput` in llama-benchy patch |
| Legacy | `speed:output_tps2048` / visible-only rows **unchanged**; scorecard exposes `output_tps` for old runs; `decode_tps` null until Speed re-run on new profile |

### Scorecard / export fields

`decode_tps`, `decode_tps_profile`, `decode_tps_method`, `decode_invalid_reason`, `decode_repetitions_valid`, `visible_decode_tps`, plus legacy `output_tps`. Borda **excludes** decode (quality axes only).

### UI

- **Models:** `DecodeSpeedInline` on card; expanded **DecodeSpeedCard** (prefill, first token, visible decode, Measured/Legacy badge); work clock in `SpeedPlate` below.
- **Compare:** **Decode tok/s** table column; radar **7th spoke** (normalized min–max in view); legend compact decode card + work clock.
- **Arena:** No fake tok/s — `tokens_per_second` null unless real token timing (provider usage heuristic removed).

### Operator notes

- **Re-run Speed** (Standard tier or axis) to populate new headline on each seat.
- Thinking models: full decode when reasoning streams are visible; **`reasoning_tokens_hidden`** when not.
- **Not built:** `decode-32k-512-c1-v1`, AIPerf/concurrency load (WP6).

### Code map

`decode_tps.py`, `runners/speed.py`, `speed_gate.py` (`speed:decode_tps*`), `scoring._extract_speed`, `tests/test_decode_tps.py`.

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
uv run pytest          # ~173 tests (includes decode + full-suite smoke tests)
cd frontend && npm run build
```

Docker image bundles frontend build. **Do not** run long tier benchmarks in CI without owner approval.

---

## 9. Live fleet context (2026-11-22, revenant)

Illustrative **owner session** (not invariant):

- **Inkling** (`inkling-2-mini-q3-prism`): Standard tier group `tier-74269a85782a`, **9/10 axes completed**, **Coding #1593 paused** (~26/40 checkpoint items when last inspected) — **Resume**, not full-tier rerun, to finish.
- **Speed** on Inkling: legacy **output_tps2048** likely null (short EOS); **decode_tps** empty until Speed re-run on **4K→512** profile. Prefill/think metrics may still be present.
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
3. Spec §1, §9.1 (compare/speed), §11 (Creative), §14 · **Addendum A** (decode)  
4. [ADR-001](decisions/ADR-001-ranking-cohorts.md), [ADR-010](decisions/ADR-010-retire-agentic-finalist-ui.md), [plans/WP5c-axis-rerun.md](plans/WP5c-axis-rerun.md)  
5. Methodology audit + response under `doc/BenchBase_Cursor_Methodology_Audit*.md`

---

## 13. Session delta (since first HANDOFF revision)

| Area | Delivered | Commits (approx.) |
|------|-----------|-------------------|
| Decode TPS Addendum A | Profile, runner, gates, scoring, CSV, tests | `50bedd5` |
| Full suite UX | Smoke→Standard chain, Models + Benchmarks button | `9adfd65` |
| Decode UX | `DecodeSpeedCard`, Compare radar spoke, Models hero | `b76e019` |

**Session delta (2026-11-23, vNext completion pass):**

| Area | Delivered |
|------|-----------|
| Full-suite restart | `_rehydrate_smoke_follow_up_watchers` + tests |
| WP5c discard UI | Rerun dialog Discard axis |
| WP3 | `llm_evidence` manifests, `EvaluatorResult` append, Alembic `20261123_0001` |
| WP4 | Diagnostics decode_tps gap + prod backup snapshot |
| WP6/32k | `decode-32k-512-c1-v1`, `tinybenchmarks` adapter |
| WP7–9 | OpenCode driver mock, worker compose, export packages, capabilities v2, SELF_HOST |

**Fleet ops:** Inkling Standard tier complete (Coding #1593 done); Speed #1598 rerun queued/completed — restart container or redeploy to pick up 32K pp config if decode rows still empty.

**Deferred / follow-ons:**

- Live OpenCode worker (`BENCHBASE_OPENCODE_LIVE=1`) after owner short test.
- Kasm/liminal preview isolation (static preview ships).
- Auto-chain **Thorough** after Standard (not requested).
- Role-based seat recommendations (discussion only).

**End of handoff.**