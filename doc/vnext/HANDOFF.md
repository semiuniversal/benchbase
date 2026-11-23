# BenchBase vNext — implementation handoff

**Date:** 2026-11-23 (natural decode TPS + actionable dashboard)  
**Authority:** [BenchBase vNext Specification v1.2](../BenchBase_vNext_Specification_v1.2.md) · [Addendum A: Decode TPS](../BenchBase_vNext_Addendum_Decode_TPS_v1.0.md) · [Dashboard headlines spec](../BenchBase_Dashboard_Actionable_Headlines_Spec_v1.0.md)  
**Living progress:** [CHECKLIST.md](CHECKLIST.md) · **ADRs:** [decisions/](decisions/README.md)  
**Git:** `main` on **revenant** (ahead of `origin/main`; recent: `54052ab` decode natural, `eec5f05` dashboard — verify with `git log -8`)

This document is for the owner and the next agent to resume work without re-deriving state from chat logs.

---

## 1. What BenchBase is today

BenchBase is a **local-model evaluation laboratory**: FastAPI + SQLite + React/Mantine UI, deployed via **`benchbase:local`** on **port 8099** (`docker/docker-compose.yml`). Inference uses an OpenAI-compatible gateway (`config/settings.yaml` → `litellm_base_url` / LLManifold).

| Mode (spec §1) | Purpose | Current maturity |
|----------------|---------|-------------------|
| **Dashboard** | Ranked **actionable headlines** → deep link into Benchmarks log | **D1 shipped** — benchmark running/completed/interrupted/queued only |
| **Benchmarks** | Quantitative tier runs (Smoke / Standard / Thorough) | **Production-ready**; queue, pause/resume, per-axis rerun, progress UI, optional **Speed (exact)** suite |
| **Compare** | Cohort scorecards, heatmap, work clock, gates, **decode tok/s** radar | **Usable**; decode spoke prefers **natural** profile; low-confidence shown but excluded from strict decode ranking |
| **Arena** | Side-by-side chat + usage semantics (WP2) | **Usable** |
| **Creative Arena** | OpenCode challenge + gallery (WP7–8) | **Feature-flagged**; not wired to dashboard (D2) |

Legacy **Agentic Finalist (OMP)** UI retired ([ADR-010](decisions/ADR-010-retire-agentic-finalist-ui.md)).

---

## 2. Position vs specification v1.2

Implementation is **partial** on WP3 evidence, Creative isolation, adapters; **strong** on benchmarks ops, comparison cohorts, **revised decode TPS**, and **dashboard D1**.

| Package | Status | Notes (2026-11-23) |
|---------|--------|---------------------|
| **WP2** Measurement | **Mostly done** | **Primary decode:** `decode-4k-natural-c1-v1` — no `exact-tg` on Standard Speed; fallbacks + confidence; exact diagnostic on **Speed (exact)** suite |
| **WP5** UX | **Partial** | **Dashboard** replaces hollow KPI/model table; DecodeSpeedCard confidence badges |
| Others | See prior table in git history | CHECKLIST for owner verification lines |

---

## 3. Architecture (as built)

```
Dashboard → GET /api/dashboard/headlines
Mantine UI → FastAPI (src/benchbase/api)
          → batch_scheduler + run_executor → runners
          → SQLite + run logs → scoring / work_clock → Compare, Models, export
```

**Key modules (new/updated this session):** `dashboard_headlines.py`, `api/routes/dashboard.py`, `decode_tps.py`, `runners/speed.py`, `scoring._extract_speed`, `frontend/.../DashboardPage.tsx`.

---

## 4. Decode tok/s (revised — natural primary)

**Product correction:** Forced-length (`min_tokens` / `ignore_eos`) is **not** required for the headline metric. See [DECODE_TPS_FRICTION.md](DECODE_TPS_FRICTION.md) and plan [plans/DECODE_TPS_SIMPLIFY_PLAN.md](plans/DECODE_TPS_SIMPLIFY_PLAN.md). **Commit:** `54052ab`.

### Profiles

| Profile | Suite | Runner | Purpose |
|---------|--------|--------|---------|
| **`decode-4k-natural-c1-v1`** | Speed / Throughput (default) | No `--exact-tg` | **Headline** decode TPS on any working route |
| **`decode-4k-512-exact-c1-v1`** | **Speed (exact)** (`axis: speed_exact`) | `--exact-tg` + LLManifold allow check | Optional diagnostic; separate from Compare headline |
| **`decode-4k-512-c1-v1`** (legacy) | Historical rows | — | Scorecard may still show gated/null results; not rewritten |

**Suite seed** (`db/session.py`): Standard `pp: [4096]` only; **32K natural deferred**.

### Measurement

- **Fallback chain:** `generated_decode` → `output_decode` → streaming `output_tg` (`select_decode_measurement`).
- **Natural valid replicate:** ≥32 generated tokens + timing; **median** headline with **`confidence: high|low`** (publish either; 1–2 valid = low).
- **Run fails** if Speed completes with **no** headline decode number (no silent `—` on finished run).
- **Strict radar/tok/s rank:** UI excludes `decode_confidence === low` / `decode_comparable_ranking === false`.

### Operator notes

- **Standard Speed:** no `verify-speed-routes` preflight.
- **Speed (exact):** still uses [SPEED_DECODE_ROUTE_PROCEDURE.md](SPEED_DECODE_ROUTE_PROCEDURE.md) and `uv run benchbase verify-speed-routes`.
- **LiteLLM:** restart/probe after rare exact runs (sticky `min_tokens` workspace rule).
- **Re-run Standard Speed** on seats to populate natural `decode_tps` (old exact-gated runs stay in DB).

### Code / tests

`decode_tps.py`, `speed_gate.py`, `runners/speed.py`, `scoring.py`, `DecodeSpeedCard.tsx`, `ComparePage.tsx`, `tests/test_decode_tps.py`, `tests/test_speed_runs_profile.py` — **199** tests green at last full run.

---

## 5. Actionable dashboard (D1)

**Spec:** [BenchBase_Dashboard_Actionable_Headlines_Spec_v1.0.md](../BenchBase_Dashboard_Actionable_Headlines_Spec_v1.0.md) · matrix [plans/DASHBOARD_HEADLINES_D0.md](plans/DASHBOARD_HEADLINES_D0.md) · **Commit:** `eec5f05`.

### Removed from homepage

- Lifetime Models / Suites / Total Runs KPI cards.
- Full models table and raw recent-runs table.

### Shipped (Phase D1)

- **`GET /api/dashboard/headlines`** — server-derived, max **8** items.
- Types: `benchmark.running`, `benchmark.queued`, `benchmark.interrupted`, `benchmark.completed` (7-day lookback).
- **One headline per `run_group_id`** (tier sitting); excludes agentic/finalist groups and archived models.
- **No** inactive-model health alerts; **no** Creative/findings placeholders (D2/D3).

### Deep links

- Destination: `/benchmarks?group=<run_group_id>&open=1` (or `run_id=` for solo runs).
- **Benchmarks** opens existing **tier log modal** via `?open=1` handler (alongside legacy `?monitor=1`).

### Frontend

- `DashboardPage.tsx` — ranked clickable headlines, 20s poll, empty state → Benchmarks / Models.

### Tests

`tests/test_dashboard_headlines.py` (group consolidation, smoke tier labeling, destination query, priority ordering).

### Not shipped

- D2 Creative review headlines.
- D3 methodology-aware Compare findings.

---

## 6. Benchmarks operator picture (unchanged core + delta)

### Tier execution

- **Order:** Smoke → … → Speed on `_TIER_AXIS_ORDER` (Speed / Throughput uses **natural** config).
- **Extra suite:** **Speed (exact)** — manual/axis launch only; not in default tier batch list.
- **Concurrency:** `batch_model_concurrency` in `config/settings.yaml`.
- **Full suite:** `POST /benchmarks/batch/start-full-suite` — Smoke → Standard chain; see prior HANDOFF text for restart caveats.

### Progress & settings

- `GET /runs/{id}/timing`, `RunProgressPanel`, `coding_execution_enabled`, `work_clock_reference_model` — unchanged.

---

## 7. Compare / Models speed UI (post-natural)

- Headline: `decode_tps` from natural profile; **`decode_confidence`**, **`decode_forcing`**, **`decode_comparable_ranking`** on scorecard speed blob.
- **Speed (exact)** optional fields: `decode_tps_exact` when a `speed_exact` sitting exists.
- Badges: **Measured** vs **Low confidence**; radar decode spoke skips low-confidence for ranking extent.

---

## 8. Creative, evidence, export

Unchanged from prior handoff: Creative behind flag; WP3/WP4/WP9 partial. No dashboard integration for Creative yet.

---

## 9. Tests & deploy

```bash
uv run pytest          # ~199 tests
cd frontend && npm run build
docker compose -f docker/docker-compose.yml build benchbase && docker compose -f docker/docker-compose.yml up -d benchbase
```

**revenant:** container **healthy** on **8099** after 2026-11-23 redeploys (decode + dashboard images).

---

## 10. Live fleet context (illustrative)

- Historical decode rows may show **gated** exact-era nulls until **Standard Speed** re-run.
- Prism/Trellis/GLM seats: natural Speed should yield **Measured** tok/s without LLManifold `allow` on Standard.
- Dashboard on prod DB may show **interrupted** + **completed** headlines for recent tier sets (`/api/dashboard/headlines` smoke-tested).

---

## 11. Safe constraints for the next agent

1. **No** historic score rewrites; **no** production DB wipe without owner.
2. **No** global LiteLLM `min_tokens`; exact-tg **only** on Speed (exact) suite.
3. **No** fabricated dashboard headlines or Creative placeholders without real routes.
4. **Mesh:** revenant; mesh-relay when tools available.

---

## 12. Session delta (2026-11-23 — this chat)

| Area | Delivered | Commits |
|------|-----------|---------|
| Decode TPS simplification | Natural primary profile, fallbacks, confidence, Speed (exact) suite, UI/radar rules, tests | `54052ab` |
| Ops | `benchbase:local` rebuild/redeploy on 8099 | deploy only |
| Dashboard D0+D1 | Headlines API, dashboard UI, benchmark deep links, tests + D0 matrix doc | `eec5f05` |
| Docs | `DECODE_TPS_SIMPLIFY_PLAN.md` status; `DASHBOARD_HEADLINES_D0.md` | in above commits |

**Deferred (explicit owner decisions):**

- 32K **natural** speed profile.
- Dashboard **D2** (Creative review), **D3** (Compare findings).
- Mass Speed re-run across fleet (owner-driven).

**Suggested next steps:**

1. Re-run **Standard → Speed / Throughput** on key Compare seats for natural `decode_tps`.
2. Spot-check Dashboard → headline → log modal → Back.
3. Use **Speed (exact)** only when diagnosing forced-512 / route allow issues.

---

## 13. Suggested reading order

1. [CHECKLIST.md](CHECKLIST.md)  
2. [DECODE_TPS_FRICTION.md](DECODE_TPS_FRICTION.md) · [plans/DECODE_TPS_SIMPLIFY_PLAN.md](plans/DECODE_TPS_SIMPLIFY_PLAN.md)  
3. [Dashboard spec](../BenchBase_Dashboard_Actionable_Headlines_Spec_v1.0.md) · [plans/DASHBOARD_HEADLINES_D0.md](plans/DASHBOARD_HEADLINES_D0.md)  
4. [SPEED_DECODE_ROUTE_PROCEDURE.md](SPEED_DECODE_ROUTE_PROCEDURE.md) (**exact suite only**)  
5. Spec §14 · Addendum A (interpret with natural-primary override above)

**End of handoff.**