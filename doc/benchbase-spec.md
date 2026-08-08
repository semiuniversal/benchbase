# BenchBase v2 — Specification

**Status:** Draft for review
**Date:** 2026-08-07
**Scope:** Suite redesign, run tiers, data model changes, Compare radar mode. No code in this document.

---

## 1. Purpose and positioning

BenchBase is a **triage tool for local model artifacts**, not a leaderboard reproducer. The unit of measurement is the *deployed artifact*: these weights, at this quantization, with these runtime parameters, served through this stack. Published benchmark numbers describe fp16 models under canonical harnesses; BenchBase measures what the user actually runs.

Design principles, in priority order:

1. **Deterministic scoring only.** No LLM-as-judge anywhere. Every score must be reproducible offline: multiple choice matching, AST comparison, code execution, rule verification.
2. **Honest uncertainty.** Every displayed score carries a confidence interval. A score without an error bar is treated as a bug.
3. **Staged effort.** Cheap rejection first. Most models never earn a full run.
4. **Configuration is part of the result.** Every run records the full serving configuration; results from different configurations are never silently merged.

## 2. What changes, what stays

| Area | Disposition |
|---|---|
| LiteLLM proxy connection | Keep as-is |
| Model discovery, health checks | **Harden** per §5.1: reachability drives status; archive filter; aggregated error reporting |
| Arena (side-by-side streaming) | Keep as-is |
| Speed/Throughput suite | Keep timed-pass mechanics; **replace "effective visible tok/s"** with the split metrics of §6.1; display per §7.4 |
| Per-suite run launching ("Run Benchmark" for one suite) | **Remove.** The tier (§3) is the only launchable unit |
| Existing suites: Reasoning (GSM8K/MMLU), Tool Use (arc/truthfulqa), Coding (HumanEval) | **Replace** per §4. Old runs exported then dropped — clean break (see §8) |
| Historical run data | **Not migrated.** Exported to spreadsheet as lab notebook, then wiped (see §8) |
| Compare tab | Extend: more columns + radar mode (see §7) |
| Run history, per-model colors, Borda ranking | Keep; radar reuses model colors |

## 3. Run tiers

Three tiers replace the current Routine/Full toggle. Tier is recorded on every run.

| Tier | Budget (7–35B class) | Contents | Purpose |
|---|---|---|---|
| **Smoke** | 1–2 min | Coherency probes (existing), 5-item format checks per axis: extractable code, parseable JSON, tool-call syntax, MC answer-letter compliance | Kill broken artifacts: bad templates, quant-induced format collapse. Pass/fail per check, not a percentage. |
| **Standard** | 5–10 min | Tiny/sampled sets per §4 (~100 items per axis where available) | Default. Directional scores with CIs. |
| **Thorough** | 20–30 min | 300–500 items per axis where the source benchmark has them | Tighter CIs for finalists and close comparisons. |

Rules:

- **The tier is the only run unit.** Individual suites cannot be launched separately; a run is model + tier + configuration. This removes the current per-suite launch path (and the partial-coverage rows it produces) and makes every run's coverage predictable. The Speed timed passes are folded into every tier (3 passes at Smoke/Standard, 5 at Thorough).
- Standard and Thorough runs **require a passing Smoke run** for the same model+configuration (override allowed, flagged in results). Rationale: the current bimodal HumanEval results (100% or 25%) are format failures polluting quality data. Smoke absorbs them.
- Item sets per tier are **fixed and versioned** (see §5), never randomly drawn at runtime. Fixed items make runs comparable across models and time, and enable paired comparison (§6).
- Time estimates scale with measured throughput from the Speed suite when available; show estimates before launch, as the current UI does.

## 4. The eight quality axes

Each axis: one suite, one 0–100 score, one radar spoke. All scorers deterministic.

| # | Axis | Source | Standard tier | Scoring | Notes |
|---|---|---|---|---|---|
| 1 | Knowledge | tinyMMLU (tinyBenchmarks) | 100 items (fixed IRT anchor set) | MC match; IRT/gp-IRT estimate + raw proportion | Report the IRT-corrected estimate as primary; raw with Wilson CI as secondary |
| 2 | Reasoning | tinyARC (ARC-Challenge anchors) | 100 items | Same as above | ARC-Easy dropped (saturated) |
| 3 | Math | tinyGSM8K | 100 items | Answer extraction (final-number match), CoT allowed | Slowest generative suite; dominates Standard runtime. Most quant-sensitive axis — the canary |
| 4 | Coding | LiveCodeBench, stratified by difficulty | 40–50 problems | Sandboxed execution, pass/fail | Filter to problems dated after the model's release when metadata allows (contamination control). HumanEval demoted to Smoke (5 problems, format check only) |
| 5 | Tool calling | BFCL stratified subset | ~125 items: 25 each from simple, multiple, parallel, irrelevance-detection, multi-turn | AST comparison against ground truth (bfcl-eval logic) | **This replaces the mislabeled arc/truthfulqa suite.** See §4.1 |
| 6 | Instruction following | IFEval subset | 50 prompts | Rule verification (verifiable constraints: word counts, forbidden tokens, formats) | Strict-mode scoring |
| 7 | Structured output | Custom BenchBase set | 30 prompts | JSON Schema validation (strict parse, no fence-stripping forgiveness at Thorough; forgiving variant scored separately) | Schemas of graded complexity: flat object → nested → arrays of objects → enums/unions. Ship as versioned fixture in repo |
| 8 | Long context | RULER-style NIAH + variable tracking | 20 tasks at 8k, 16k, 32k (skip lengths beyond model/context limit) | Exact-match retrieval | Exposes KV-cache quantization effects. Score = mean over lengths attempted; record per-length breakdown |

Dropped from current app: TruthfulQA (contested methodology, low triage value), HellaSwag and ARC-Easy (saturated, non-discriminative), MMLU-high-school-math as a standalone (subsumed by axes 1 and 3).

### 4.1 Tool calling suite (the impetus)

- **Dataset:** vendored, versioned snapshot of BFCL test cases (Apache-2.0), stratified as above. Do not fetch at runtime.
- **Harness:** calls go through the same OpenAI-compatible endpoint (LiteLLM) as every other suite, using the standard `tools` parameter. If the model/proxy rejects the `tools` parameter, fall back to prompt-embedded schema (BFCL "prompting" mode) and **record which mode was used** — scores from the two modes are not comparable and must be labeled in the UI.
- **Scoring:** AST match on function name + argument structure with BFCL's type-aware comparison (accept `3` for `3.0`, order-insensitive named args, etc.). Reuse `bfcl-eval`'s checker if the dependency is acceptable; otherwise reimplement the checker for the five sampled categories only.
- **Irrelevance category is mandatory.** A model that calls tools when it shouldn't is agent-hostile; this is half the signal.
- **Known sensitivity:** tool-call scores vary with chat template and serving stack more than any other axis. This is by design — BenchBase measures the artifact as served — but the run's recorded configuration (§5) must make the stack visible wherever the score is displayed.

## 5. Data model changes

Minimum additions; storage layer unchanged otherwise.

### 5.1 Model discovery and lifecycle

Current defects addressed: deactivated models remain shown as running though unreachable; the model list clutters with historical models; discovery raises a single oversized error dialog enumerating every model that has ever existed.

**Model states.** Every known model is in exactly one state:

| State | Meaning | Set by |
|---|---|---|
| `active` | Present in the endpoint's current model list **and** passed its last health probe | Discovery + health check |
| `unreachable` | In the current list but failing probes, or missing from the list while still marked active | Health check; a model missing from two consecutive discoveries transitions here automatically |
| `archived` | User-hidden. Excluded from pickers, discovery probes, and health checks. **All run data retained** and still visible in Compare/history when explicitly included | User action in Settings |

Rules:

- Discovery reconciles against the endpoint's *current* `/models` response only. Models absent from it are never probed — this is the source of the mass-error dialog and of stale "running" indicators. Absent models transition to `unreachable` (or stay `archived`).
- A run can only be launched against an `active` model; the picker shows only `active`.
- Health status shown in Settings is timestamped ("as of 12:42"), never presented as live.
- Settings gains a state filter (default: active + unreachable; toggle to show archived) and bulk archive. Archive is reversible; the existing Remove (delete) stays but is demoted behind a confirmation that states run data will be lost.

**Error reporting.** Discovery/health errors never raise a modal per model. One summary panel: "Discovery complete — 4 active, 2 unreachable, 26 archived (skipped)", expandable to a scrollable per-model detail list with the underlying error text truncated to one line each, full text on click. Errors for `archived` models are not collected at all.

**Suite definitions are versioned.** `suite_id` + `suite_version` + content hash of the item set. A score is meaningless without knowing which items produced it. Bumping an item set bumps the version; cross-version comparisons are blocked in Compare (shown greyed with a tooltip, not silently mixed).

**Runs store per-item results,** not just aggregates: item id, pass/fail (or raw extracted answer), latency. Enables: CIs computed at read time, paired model comparison (§6), post-hoc rescoring when a checker bug is fixed, and "show me the items it failed" drill-down.

**Runs store full configuration:** model id, base-model id (see below), quantization label, serving backend and version (from LiteLLM model info where available), temperature/top_p/max_tokens, chat-template identifier if known, tool-call mode (§4.1), tier, suite versions.

**Base-model grouping.** New field `base_model`, auto-parsed from model name (strip quant/variant suffixes: `-int4-autoround`, `-nvfp4`, `-nothink`, `-q4_k_m`, ...), user-correctable in Settings (same pattern as the existing color picker). Powers the family/rings view (§7.3). Parser failures default to base = full name; never guess across dissimilar names.

**Quant ordering.** Per base model, an ordered list of its variants by nominal precision (fp16 > q8 > q6 > q5 > q4 > ...), auto-derived from the label with manual override. Powers ring ordering.

## 6. Scoring and statistics

### 6.1 Speed metrics (replacing "effective visible tok/s")

The composite "effective visible tok/s" (visible tokens ÷ wall time including think time) is retired: it penalizes reasoning models by an amount that depends on prompt difficulty, making it neither a throughput number nor a latency number. Replacement: measure the phases separately and don't blend them.

| Metric | Definition |
|---|---|
| `ttft_ms` | Request start → first token of any kind (thinking or output) |
| `think_tokens`, `think_ms`, `think_tps` | Thinking/reasoning phase, when the model emits one (detected via reasoning-content field or think-tag parsing; mode recorded) |
| `output_tokens`, `output_ms`, `output_tps` | Visible output phase only: output tokens ÷ output-phase time |
| `prefill_tps` | Prompt tokens ÷ prefill time (PPS), as currently measured |
| `total_ms` | Wall time, start → last token (the honest end-to-end number) |

Rules: `output_tps` is the headline throughput figure everywhere. Think cost is displayed as its own quantity ("+14 s think, 210 tok"), never folded into a divisor. Non-reasoning models simply have null think fields. The old composite metric does not exist in v2 (clean break, §8); it survives only in the exported lab-notebook spreadsheet.

- **Primary score per axis:** proportion correct (or IRT estimate where tinyBenchmarks calibration exists), displayed 0–100 with one decimal maximum.
- **Uncertainty:** Wilson 95% interval on the raw proportion. Displayed everywhere the score is: table cells (`62 ± 4`), radar (optional band, §7.2), tooltips. IRT estimates display the tinyBenchmarks published error as their band.
- **Paired comparison.** When two models have runs on the same suite version, Compare may show a head-to-head verdict per axis computed by McNemar's test on the shared items: "A > B (p<0.05)", "no detectable difference", or "insufficient data". This is the statistically cheap comparison that fixed item sets buy us; surface it in the table as a small marker rather than a new view.
- **Aggregation.** Overall ranking stays Borda across axes (existing mechanism), computed over quality axes only. Speed never enters Borda; it is its own ranked column.

## 7. Compare tab

### 7.1 Table mode (extended)

Columns: Model · Overall (Borda) · eight axis columns · Speed (effective visible tok/s) · TTFT. Each axis cell: score ± CI, rank badge (existing style), run count. Cells with no runs: em dash, not zero. Cells from mismatched suite versions: greyed with tooltip.

### 7.2 Radar mode (new)

- Toggle Table ⇄ Radar, top-right of the scorecard.
- **Axes:** the eight quality axes, fixed order (as §4 table), 0–100 scale. **Speed and TTFT are never radar axes** — they appear as a compact badge row per model below the chart (reuse Arena badge styling).
- **Overlays:** up to 6 models, using each model's assigned color from Settings. Line style varies per model in addition to color (solid/dash patterns) for color-vision accessibility.
- **Scale modes:** default **Absolute** (0–100). Optional **Stretch differences** toggle: per-axis min–max normalization across the selected models, with the axis labels then showing the true min/max values so the distortion is legible. The toggle state is visibly labeled on the chart ("stretched — differences amplified").
- **Missing data:** the polygon has a **gap** at any axis without a valid run — never interpolated, never zero. Legend marks such models "partial".
- **Uncertainty (optional toggle):** per-model translucent band at ±CI. Off by default; bands overlap badly beyond 3 models — disable the toggle at 4+.
- **Hover:** axis hover shows per-model score ± CI and run count; click-through to the runs behind it.

### 7.3 Family mode ("tree rings")

- Entered by selecting a **base model** instead of individual models (picker gains a "group by family" switch).
- Shows one hue (the family's color) in ordered shades: highest precision = darkest outer ring, descending quants progressively lighter inward. Same gap/CI rules as §7.2.
- Purpose: answer "at which quant does this model exit viability for my use case?" A **viability floor** overlay (user-defined threshold per axis, default off; e.g. tool calling ≥ 60) renders as a shaded inner region; any ring crossing into it is flagged in the legend.
- Family mode and multi-model mode are mutually exclusive on one chart (mixing distinct-hue and shade grammars on one radar is unreadable).

### 7.4 Speed display (prominent, off-chart)

Speed is the co-equal headline next to capability, but never a radar axis. In both Compare modes, each model gets a **speed plate**: `output_tps` rendered as a large number whose size and color encode magnitude.

- **Size:** three tiers by `output_tps` — small (<20), medium (20–60), large (>60). Thresholds configurable in Settings; defaults tuned for single-node local serving.
- **Color:** sequential single-hue ramp (slow = pale, fast = saturated), never red/green alone; the number itself always readable in both themes.
- **Secondary line, small:** `prefill_tps`, `ttft_ms`, and — when present — think overhead ("+14 s · 210 think tok"). These stay visible because a model with great output_tps but 2,500 ms TTFT or heavy think overhead feels slow in use.
- The plate appears: under each model's name in radar mode, in the Speed column in table mode, and on the Dashboard model cards.

## 8. Migration — clean break

No legacy data is carried into v2. Rationale: old runs were produced by mislabeled suites, tiny ad-hoc samples, and the deprecated composite speed metric; they have archival value as a lab notebook but would contaminate every comparison view they touched, and supporting them costs a `legacy` flag on every query path.

- **Pre-upgrade export, then wipe.** Before first v2 launch, the app offers (or the user performs manually) a full export of the existing board: one spreadsheet with a runs sheet (all runs, scores, timestamps, configs as recorded) and a models sheet. The export is the lab notebook; v2 starts with an empty run store.
- Model registry (names, colors, base-model assignments) **may** carry over — it's configuration, not results. Archived/stale models from §5.1 cleanup can be dropped at the user's option during import.
- v2 schema carries no legacy-compatibility fields. Suite versioning (§5) starts at v1 for every suite.

## 9. Non-goals

- τ-bench-style simulated-user agentic evaluation (requires judge/simulator LLM; stochastic; violates principle 1).
- LLM-judged writing quality, helpfulness, or chat quality.
- Reproducing leaderboard numbers. Divergence from published scores is expected and documented, not a bug.
- Safety/refusal benchmarking.

## 10. Assumptions and open questions

Assumptions (spec written from UI screenshots; codebase not inspected):

- A1. Runs and results live in a store that can accommodate per-item rows (§5) without a rewrite.
- A2. Suites are defined in code/config that can carry a version field.
- A3. The LiteLLM endpoint passes through the `tools` parameter for models that support it.
- A4. A sandboxed execution path exists or can be added for coding suites (current HumanEval suite implies one exists).

Open questions for the author:

- Q1. Coding sandbox: is current HumanEval execution containerized? LiveCodeBench needs stdin/stdout harness per problem — same mechanism or new?
- Q2. Long-context suite at 32k on large local models can dominate the Thorough budget. Cap Standard tier at 16k?
- Q3. Vendor tinyBenchmarks IRT weights (small, MIT) or take the Python package dependency?
- Q4. Is dark mode parity required for the radar at launch? (Radar bands and shade ramps need a dark palette pass.)
- Q5. Structured-output fixture (30 schemas): author in-repo, or generate once and freeze? Recommend author + freeze with the suite version.

## 11. Acceptance criteria (per feature, testable)

1. A Standard run on a 7B-class model at ~40 tok/s completes all eight axes in ≤ 10 minutes.
2. Every score rendered in Compare shows a CI or an explicit "n too small" state.
3. Tool-calling suite: a model that emits syntactically valid but wrong-function calls scores below one that calls correctly and declines irrelevant requests; both distinguishable from a model that fails to emit tool syntax at all (which fails Smoke instead).
4. Radar gap behavior: removing a run from a model's only Coding row produces a visible polygon gap, not a zero spike.
5. Family mode renders ≥ 3 quants of one base model as ordered shades with correct precision ordering from the parser or manual override.
6. Two models with identical configs and a shared suite version show a McNemar verdict in table mode.
7. After the clean break, no pre-v2 run appears in any view; the export spreadsheet contains every pre-v2 run with its original scores and metric names.
8. Stopping a model at the endpoint results in its status showing `unreachable` after the next health cycle; no model ever displays as active/running while failing probes.
9. Archiving a model removes it from all pickers and probe cycles without deleting any run data; unarchiving restores it fully.
10. A discovery pass over 30+ known models with 26 stale produces one summary panel, no per-model dialogs, and no probe traffic to archived models.
11. For a reasoning model, Compare shows `output_tps` excluding think time, with think cost displayed separately; no view anywhere blends think time into a throughput figure.
12. Per-suite launch UI is gone; the only run buttons are the three tiers.
