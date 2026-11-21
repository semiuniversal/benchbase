# BenchBase methodology audit — response report

**Audit requested:** `doc/BenchBase_Cursor_Methodology_Audit.md` (2026-11-21)  
**Repository commit investigated:** `8543f6fd82c9133d3ab4aa954dd28b5665e80a82` (`main`, 4 commits ahead of `origin/main`)  
**Uncommitted local files at investigation time:** `doc/BenchBase_Cursor_Methodology_Audit.md` only (untracked)  
**Mode:** Read-only code and corpus review; no benchmarks executed; no database opened for this report.

---

## Executive summary

### Confirmed (code-backed)

- **Standard tier item counts** for the current corpus (`suite_version` **v2** on most axes, **v3** on `long_context`) match the export table: smoke uses the **first *N*** rows of each frozen `items.json`; standard uses fixed caps (e.g. knowledge 100, tool calling 125, coding 40, long context **57** items after length filter). Selection is **not re-seeded per run** — `select_tier_items` takes a prefix (`quality_common.py` ~95–105).
- **Scores on quality axes are plain pass rates** on that frozen subset, with **Wilson 95% intervals on successes/planned_n** (`stats.wilson_interval`, `quality_common._score_from_items` ~410–433). They are **not** tinyBenchmarks IRT full-benchmark estimates; manifests explicitly mark **`irt_deferred: true`** (e.g. `corpus/suites/knowledge/v2/MANIFEST.json`).
- **Overall rank and CSV export** use one **global Borda pool** over all non-archived models with any Borda points. **`best_tier`** comes from `pick_sitting` (latest complete Standard/Thorough sitting, else Smoke) but **does not gate export ranking** — only the Compare UI can hide smoke via `matchesCompareDisplay` (`frontend/src/components/comparison/compareSelection.ts` ~19–33).
- **Borda formula in scorecards:** per-axis points = `competitors - rank` (`scoring._borda_points` ~265–266); overall = sum over **six** radar axes only; structured/long_context contribute **rank for export** but **`borda_points` are forced to 0** on gates (`scoring._build_scorecards` ~402–406).
- **Missing `output_tps` in CSV** while Arena shows tok/s is **expected** when Speed runs gate out decode throughput (short EOS, failed replicate validity) or produce **no visible output tokens** under llama-benchy’s thinking split (`speed.py` ~121–161, ~178–183; `speed_gate.py`).
- **Long-context “gate” in UI** = `primary >= 100` (`scoring.gate_pass` ~51–55). Partial scores (e.g. **71.9% ≈ 41/57**) are normal axis percentages, not a failed gate.
- **Proxy integration** is **OpenAI-compatible HTTP** (`LiteLLMClient`); discovery uses `/v1/models` and optionally LiteLLM **`/model/info`**. LLManifold exposes `context_length` on `/v1/models` but often **no `/model/info`** — context may stay empty unless the client reads `context_length` or the operator sets `context_window_manual`.

### Suspected / plausible explanations for export anomalies (not proven without DB replay)

- **Smoke-only models in top overall ranks:** valid under current rules if they have the only **complete** sitting and strong axis scores; reranking on Standard-only is a **post-export analytics** step, not what the app exports by default.
- **Tool-calling band 52–67%:** fixture is **125 binary items** with strict name+args matching; clustering is consistent with **hard ceiling** on this harness, not necessarily a single bug.
- **Coding 0 vs ~52.5 on think/nothink pairs:** plausible mix of **thinking tokens eating budget**, **code extraction failure** (`coding._extract_python`), timeouts, or real capability gap; needs **`result_items` + run logs** for named models (not run here).
- **Extreme TTFT on Qwen4 Exp Side:** likely **server-reported or benchy e2e TTFT** on pathological runs; `speed_gate.prefill_invalid_reason` may null prefill when inconsistent — check stored `raw_output_json` on Speed `Result` rows.

### Unknowns / evidence gaps

- Per-deployment **raw item transcripts** for the Qwen 3.6 35B coding-0 cases (requires production SQLite + run_id lookup).
- Whether export’s **55 unscored rows** are unreachable, never benchmarked, **incomplete run groups**, or **version-mismatched** axes (mechanism is known; cohort breakdown needs DB).
- **Cold-start / thermal / concurrent load** on inference hosts — **not recorded** in BenchBase.

### Strengths to preserve

- **Frozen corpus + `content_hash` + `suite_version`** per axis; version mismatch **excludes from ranking** without deleting history.
- **Per-item checkpointing** (`result_items`) enabling pause/resume and potential **rescore-without-inference** for many axes.
- **Operational UX:** live Q/A log, Wilson CIs, tiered smoke/standard/thorough, work-clock metric, Arena, Borda/radar, CSV export.

---

## 1. Architecture, persistence, and execution path

### Annotated source tree (application)

```
src/benchbase/
  main.py                    # FastAPI app
  api/routes/
    benchmarks.py            # tier launch, batch queue, SSE logs
    models.py                # discover/recheck, CRUD
    results.py               # scorecard, radar
    arena.py                 # multi-model streaming
    settings.py
  batch_scheduler.py         # run_group_id, axis order, concurrency
  run_executor.py            # single Run lifecycle, active_ms
  work_clock.py              # pick_sitting, n_correct, suite wall
  scoring.py                 # scorecard, Borda, gates
  stats.py                   # Wilson, McNemar
  litellm_client.py          # OpenAI-compatible proxy client
  db/models.py, db/session.py
  runners/
    quality_common.py        # chat, persist, Wilson, tier items
    knowledge.py … long_context.py, speed.py, smoke.py, agentic.py
corpus/suites/<axis>/<version>/items.json, MANIFEST.json
frontend/src/                # Mantine UI, Compare, CSV export
```

### End-to-end flow (tier launch → export)

1. **User** starts tier on Benchmarks UI → API creates a **`run_group_id`** and one **`Run` per axis** (`batch_scheduler.py` ~27–39 axis order: smoke → … → speed).
2. **`execute_run`** loads runner, sets status, **`RunLogManager`** streams progress (`run_executor.py` ~43+).
3. Runner calls **`LiteLLMClient.chat`** (or llama-benchy / OMP subprocess for speed/agentic).
4. **`run_quality_items`** checkpoints **`ResultItem`** rows; **`finalize_axis_result`** writes aggregate **`Result`** with score, Wilson CI, `metrics_json.successes`.
5. **`compute_model_scorecard`** picks **`pick_sitting`**, pulls only **current `suite_version`** results into `axis_runs`, builds dimensions + Borda (`scoring.py` ~128–227, ~311–431).
6. **CSV** serializes full scorecard array (`exportScorecardCsv.ts` ~45–76) — no smoke filter.

### Data entities (schema)

| Entity | Role |
|--------|------|
| `Model` | Canonical **seat name** (unique), `endpoint_url`, optional `context_window` / manual override, `litellm_model_info_json` |
| `BenchmarkSuite` | Axis, `runner_class`, **`suite_version`**, `content_hash` |
| `Run` | `model_id`, `suite_id`, **`run_group_id`**, **`tier`**, `status`, `metadata_json` (eval mode, `active_ms`, invalid_reason) |
| `Result` | Axis aggregate: `task_name`, `score`, `ci_low`/`ci_high`, `n_items`, `metrics_json`, optional `raw_output_json` |
| `ResultItem` | `item_id`, `passed`, **`raw_answer`** (truncated), `latency_ms`, `detail_json` |

**Relationships:** Model 1—* Run; Run 1—* Result 1—* ResultItem. Sitting = all Runs sharing `(model_id, run_group_id)`.

### Model identity vs alias

- **One row per discovered proxy model id** (`models.name` unique). Discover **renames** to match proxy id (`models.discover_models` ~512–524).
- **No automatic fork** when upstream weights change under the same name — operator must add a new seat or notes. **`base_model` / `quant_rank`** are inferred from name heuristics, not cryptographically bound to weights.
- **`context_window_manual`** blocks rediscovery overwrite (`models._apply_litellm_info` ~167–177).

### Versioning and compatible runs

- **Pinned per axis** in DB `benchmark_suites.suite_version` (seeded in `db/session.py`; long_context **v3**, others **v2**).
- Scorecard uses sitting runs’ versions but **only ranks `axis_runs` where `suite_version == current`** (`scoring.py` ~322–324, ~195–196). Older runs remain in DB and in `all_results` but set **`version_mismatch`** / **`excluded_from_ranking`**.

### Best tier, mixing axes, export scope

- **`pick_sitting`:** latest **complete** sitting where all eight work-clock axes finished; prefer **standard/thorough** over smoke (`work_clock.py` ~128–135).
- **Cannot mix axes from different run groups** in one sitting — single `run_group_id`.
- **55 unscored export rows (hypothesis):** any registered non-archived model with **no complete sitting**, **incomplete group**, **all axes excluded**, or **zero Borda** still appears in CSV with empty scores; `best_tier` may be null while `has_benchmark_history` is true if **any** completed run exists (`scoring.py` ~208–209).

### Retention for rescoring

| Retained | Not retained (typical quality axis) |
|----------|-------------------------------------|
| Item id, pass/fail, extracted answer, reason, latency | Full **multi-turn** message list sent to API |
| `raw_answer` capped (~500–1000 chars in runners) | Complete reasoning stream (unless in truncated raw_answer) |
| Speed: full llama-benchy JSON in `Result.raw_output_json` | Arena comparisons (not persisted) |
| Run text logs on disk (`run_log`) | Effective per-request `max_tokens` after headroom unless logged |

**Rescore without inference:** feasible for axes with **`result_items`** if scorer logic changes (class 2). Changing **prompts/items** requires new suite version (class 3).

### Proxy dependencies

- Settings field remains `litellm_base_url` / API key; UI label is **model proxy base URL**.
- Metadata: **`GET /model/info`** (LiteLLM) or fallback **`/v1/models`** (`litellm_client.model_info_map` ~47–87). LLManifold: **`context_length`** on list rows; **`/model/info` often 404** (documented in prior ops note).

---

## 2. Benchmark-by-benchmark protocol table

Tier counts are **prefix selection** from frozen `corpus/suites/<axis>/v2/items.json` unless noted. **Evaluation mode:** single-turn chat completion, `temperature=0`, `max_tokens` per runner + **`THINKING_HEADROOM = 2048`** on quality calls (`quality_common.py` ~35–38, ~198–202). **Scoring:** `successes / planned_n * 100` + Wilson on that fraction — **not** population inference to full upstream benchmarks.

| Axis | Upstream (MANIFEST) | Standard n | Scorer | Stored score |
|------|---------------------|------------|--------|--------------|
| Knowledge | tinyBenchmarks/tinyMMLU anchors (100 ids listed) | 100 | MC letter extract vs key | % correct + Wilson |
| Reasoning | tinyARC-style fixtures | 100 | Same MC | % + Wilson |
| Math | tinyGSM8K-style | 100 | `extract_final_number` vs answer | % + Wilson |
| Coding | LiveCodeBench lite, ≥2024-01-01, **public tests only** | 40 | Python extract + **local python3** stdin/func exec | % + Wilson |
| Tool calling | BFCL v3 subset, 25×5 categories | 125 | OpenAI **tools** first, else JSON parse; binary pass | % + Wilson |
| Instruction | IFEval-**style** rules in fixtures | 50 | Custom `check_rule` types | % + Wilson |
| Structured | JSON schema tasks | 30 | Subset JSON Schema validator | % + Wilson |
| Long context | NIAH / multi-needle / tracking (v3: **57** items after filter) | 57 | Exact needle match heuristics | % + Wilson; gate at 100% |
| Smoke | Format/coherency checks | 25 | Pattern checks (code fence, JSON, tool shape) | Tier gate, not Borda |
| Speed | llama-benchy | config `runs` | Throughput metrics + gates | Separate from Borda |

### tinyBenchmarks / tinyMMLU

- **Items:** Frozen JSON derived from anchor ids in MANIFEST; **`irt_deferred: true`** — **no IRT estimator** in code path.
- **Method:** **Answer-letter generation** (not log-likelihood). Prompts are in fixtures; **`extract_mc_letter`** with unparseable → fail (`quality_common.py` ~108–142).
- **Smoke ⊆ standard:** smoke = **first 5** items of same list; standard = **first 100** (`knowledge.py` ~80).
- **Wilson:** on **observed passes / planned_n** for that subset — **not** uncertainty for full MMLU.

**GSM8K / console `A:`:** Live log shows **`raw_answer`** after extraction when present (`progress_log` + runner returns `extracted` in detail). Math runner stores **`got or text`** — console may show **numerals only** when extraction succeeded (`math.py` ~52–58).

### LiveCodeBench (coding axis)

- **Not full LCB harness:** curated **45** items, **public stdin tests only** (`coding/v2/MANIFEST.json`). Standard runs **40**.
- **pass@1** style: one solution, execute once; timeouts **3s / 2s** (`coding.py` ~47–78).
- **Extraction:** fenced `python` block or heuristic `def`/`print`; rejects prompt echo (`coding.py` ~29–44).
- **Thinking models:** long wall times plausibly from **2048+ token generations** before visible code; **0%** consistent with systematic **unparseable** or **timeout**, not proven here.

### BFCL (tool_calling)

- **Version:** BFCL v3 per MANIFEST; **125** items, categories in notes.
- **Native tool calls** when API accepts `tools`; else **prompting** (`tool_calling.py` ~166–193). **Binary** item pass.
- **Schema:** `_normalize_json_schema` fixes non-OpenAI types (e.g. `float` → `number`) before calls — infra errors can **pause** run (`is_infra_error`).
- **Narrow score band:** consistent with **strict arg match** and hard subset; category breakdown in `detail.category` per item.

### IFEval, structured, long context

- **IFEval:** **Inspired** rule types implemented in `instruction.check_rule` — **not** a claim of vendored Google IFEval runner verbatim.
- **Structured:** prompt-only JSON; **Thorough** may use stricter stripping (`structured.py` ~87–99). **No** constrained decoding.
- **Long context:** **Fixed** nominal lengths **8000 / 16000 / 32000** (token field × ~4 chars filler); **not scaled** to each model’s advertised context (`long_context._select_items` ~97–102). **Same workload** across endpoints → scores are **comparable as “same stress test”**, not “fraction of model max context.”
- **71.9% (Q2 Prism):** interpret as **~41/57** items passed on v3 schedule; **configured 262144** is **metadata**, not proof all 57 items used full window (most items ≤32k nominal).

### Smoke / format coherency

- **First axis** in a tier batch (`batch_scheduler._TIER_AXIS_ORDER`). **25** fixture items (`smoke.py` ~77–80).
- **`WORK_CLOCK_AXES`** covers eight quality axes (knowledge through long_context) and **does not include smoke** (`work_clock.py` ~25–34). Work-clock `n_correct` and sec/correct therefore exclude the smoke suite even when a tier run completed smoke first.
- Smoke is **not** on the six-axis radar or in Borda sums; it is an operational **format/coherency** check before heavier axes.

---

## 3. Inference, performance metrics

### Benchmark API params

- Quality: `LiteLLMClient.chat`, `max_tokens` + **2048 headroom**, `temperature=0`, optional `tools`.
- Speed: subprocess **llama-benchy** with `--exact-tg`, uses **global settings `litellm_base_url`**, model id = seat name (`speed.py` ~33–37, ~55).
- Arena: **streaming**, optional `max_tokens` from client; vision cap 16384 (`arena.py` ~30–33).

### Metric definitions (scorecard / CSV)

| Metric | Definition (implemented) |
|--------|-------------------------|
| **TTFT** | From speed results: thinking-aware resolver in speed runner metrics (`_resolve_ttft`); may include queue/e2e from benchy |
| **Prefill tps** | llama-benchy `pp_throughput`; nulled if `prefill_invalid_reason` |
| **Output tps** | **Visible output tokens ÷ output-phase time** (thinking stripped in benchy patch); nulled if `gate_decode_replicates` fails (`speed.py` ~121–161) |
| **Arena tps** | **Stream chunk count / elapsed after first content chunk** — not usage API (`arena.py` ~270–287) |
| **sec_per_correct** | Sum axis **active_ms** (or wall) / **`n_correct`** successes across 8 axes (`work_clock.py` ~98–121) |
| **speed_index** | `reference_sec / candidate_sec * 100` same tier, valid clocks, optional reference in settings (`work_clock.compute_speed_index` ~167–191) |

**Why eight lack output_tps:** gated Speed `Result.score is None` for `speed:output_tps*` tasks → `_extract_speed` omits (`scoring.py` ~498–502). Arena is independent measurement.

**Environmental controls:** **None** systematic. Concurrency: `batch_model_concurrency` (settings). No GPU telemetry in BenchBase.

---

## 4. Aggregation, comparison, uncertainty

- **Radar:** six axes 0–100 (absolute) or rank-normalized in UI; gates on separate pass/fail badges.
- **Borda overall:** sum six axis Borda points; models with **0** excluded from rank denominator.
- **CSV rank:** sorts by **`overall_rank`** from **global** pool — **includes smoke-best models** unless consumer filters `best_tier`.
- **Compare `Include smoke results`:** **view filter only** (`compareSelection.matchesCompareDisplay`).
- **Wilson:** independent-item assumption on **fixed subset**; **no** adjustment for stratified LCB difficulties or correlated long-context needles.
- **Ceiling effects:** structured/long_context **100% for many** → gates saturate; knowledge/reasoning/math **high medians** on strong local models → radar compression.

**Recalculate Standard-only ranks:** export consumer filters `best_tier === 'standard'` and recomputes Borda — **no DB change** (matches auditor’s manual recomputation).

---

## 5. Agentic bench and Arena

- **Agentic:** **Oh My Pi (`omp`)** driver, tasks under `corpus/agentic/`, `agentic/runners/agentic.py`; persists transcripts paths, **T_eff** metrics; **finalist** tier separate from six-axis radar.
- **Arena:** ephemeral parallel streams, **no DB persistence**; reusable patterns for live inspector only.
- **LiveCodeBench vs agentic:** LCB axis = **single-shot code**; agentic = **multi-turn tool/file** harness.

---

## 6. Historical compatibility and fix taxonomy

| Issue | Class | Notes |
|-------|-------|------|
| CSV smoke+standard rank | **1** Presentation / export filter | Compare already filters |
| Wilson misinterpretation | **1** Docs / export metadata | Label as subset CI |
| Version mismatch exclusion | **1** Already implemented | Old runs visible, not ranked |
| Scorer bug with stored items | **2** Rescore | `result_items` present |
| Item set / prompt change | **3** New `suite_version` | Append-only runs |
| New router fairness metric | **4** New metric | Legacy valid on old axes |
| Contaminated group `tier-99b1925bd139` | **2/1** | Hard-coded invalid_reason (`work_clock.py` ~36–39) |

**No database reset** required for improvements. Backups: Docker volume `data/benchbase.db` + WAL.

---

## 7. Targeted notes on export observations

| Observation | Implementation explanation |
|-------------|---------------------------|
| Identical 602 total items | Fixed `planned_n` per axis × standard tier |
| Borda = 42 − rank | Matches `_borda_points(rank, 42)` when 42 competitors on axis |
| Top ranks smoke-only | `pick_sitting` fallback + global Borda without tier filter |
| Tool band 52–67% | Binary 125-item harness |
| Coding 0 vs 52.5 think pairs | Check extraction, timeouts, thinking in `raw_answer` (DB) |
| Missing output_tps list | Speed gate / no visible decode tokens |
| Q2 71.9% long context | Partial % on 57-item v3 filter, not gate pass |
| speed_index missing | No reference, tier mismatch, `invalid_reason`, or `n_correct` drift |
| Arena 61.85 tps vs blank CSV | Different code paths (chunk rate vs gated benchy) |

---

## 8. Prioritized recommendations

| Pri | Item | Sev | Class | Acceptance |
|-----|------|-----|-------|------------|
| P0 | Document that scores are **subset pass rates**, not tinyBenchmarks IRT | High | 1 | MANIFEST + export README |
| P0 | CSV export option: **`best_tier=standard` rank column** | Med | 1 | Column matches filtered recomputation |
| P1 | LLManifold **`/model/info` compatibility** or documented `context_length` | Med | 4 ext | Discover fills context |
| P1 | Export **axis `suite_version` + `excluded_from_ranking`** per model | Med | 1 | Auditor can explain unscored |
| P2 | Tool-calling **category breakdown** in CSV | Low | 1 | Mean pass rate per BFCL category |
| P2 | Speed: store **why output_tps null** in CSV | Low | 1 | `speed_invalid_reason` populated |
| P2 | Long-context **per-length columns** already in metrics — surface in export | Low | 1 | Join `per_length` from metrics |
| P3 | Headless AIPerf adapter behind Speed runner | Low | 4 | Optional sidecar, no UI break |

**Files (primary):** `scoring.py`, `exportScorecardCsv.ts`, `quality_common.py`, `corpus/suites/*/MANIFEST.json`, `litellm_client.py`, `speed.py`, `speed_gate.py`, `work_clock.py`.

---

## 9. Questions for the owner (evidence not in repo alone)

1. Can you provide **run_group_id** or **export row IDs** for the Qwen 3.6 35B coding-0 vs nothink pairs for item-level replay?
2. Confirm **production DB** `benchmark_suites` row for long_context is **v3** (57 items) on the export date.
3. For the eight **missing output_tps** models, do Speed runs show **`Speed gate: discarded numeric`** in run logs?
4. Is **CSV intended for public ranking** (smoke+standard) or internal fleet ops (standard-only)?

---

## 10. Source index (commit `8543f6f`)

| Topic | Path | Symbols (approx. lines) |
|-------|------|-------------------------|
| Tier item caps | `src/benchbase/runners/quality_common.py` | `select_tier_items` 95–105 |
| Wilson / pass rate | `src/benchbase/runners/quality_common.py` | `_score_from_items` 410–433 |
| Wilson math | `src/benchbase/stats.py` | `wilson_interval` 9–22 |
| Sitting / best tier | `src/benchbase/work_clock.py` | `pick_sitting` 128–135, `n_correct` 116–121 |
| Scorecard / Borda | `src/benchbase/scoring.py` | `compute_model_scorecard` 128–227, `_build_scorecards` 311–431, `gate_pass` 51–55 |
| MC knowledge | `src/benchbase/runners/knowledge.py` | tier_n 80, `_run_mc_axis` 26–69 |
| Math extract | `src/benchbase/runners/math.py` | `score_one` 42–58 |
| Coding exec | `src/benchbase/runners/coding.py` | `_extract_python` 29–44 |
| BFCL | `src/benchbase/runners/tool_calling.py` | `score_one` 166–222 |
| Long context | `src/benchbase/runners/long_context.py` | `_select_items` 97–102, `_bury` 36–47 |
| Speed / missing tps | `src/benchbase/runners/speed.py` | output_tps block 121–183 |
| Speed gates | `src/benchbase/speed_gate.py` | `gate_decode_replicates`, `MIN_DECODE_TOKENS` |
| Arena tps | `src/benchbase/api/routes/arena.py` | ~270–287 |
| CSV export | `frontend/src/components/models/exportScorecardCsv.ts` | full scorecard sort 78–85 |
| Compare smoke filter | `frontend/src/components/comparison/compareSelection.ts` | `matchesCompareDisplay` 19–33 |
| Schema ORM | `src/benchbase/db/models.py` | `Model`, `Run`, `Result`, `ResultItem` 72–213 |
| Batch flow | `src/benchbase/batch_scheduler.py` | `_TIER_AXIS_ORDER` 27–39 |
| tinyMMLU manifest | `corpus/suites/knowledge/v2/MANIFEST.json` | `irt_deferred` |
| Controls | `src/benchbase/controls.py` | `CONTROL_MODEL_NAMES`, invalid scorer gate |
| Proxy client | `src/benchbase/litellm_client.py` | `model_info_map` 47–87 |

---

*This report describes implemented behavior as of the cited commit. It does not certify external benchmark fidelity to upstream papers or leaderboards.*