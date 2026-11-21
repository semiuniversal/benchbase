# BenchBase — implementation audit questions for Cursor

**Purpose:** Determine what BenchBase actually measures, whether comparisons are valid, and how to improve the evaluation methodology without sacrificing historical observations or its existing Mantine UX.

**Mode: read-only investigation.** Do not modify application code, data, migrations, benchmark assets, or configuration. Do not run benchmarks, call inference endpoints, or expose secrets. Return a Markdown report with findings, exact source paths, function/class names and line ranges (relative to the current commit). Include short verbatim excerpts of critical logic. Distinguish implemented behavior, intended behavior, hypotheses, and unknowns. Identify the checked-out Git commit and any relevant uncommitted changes without altering them. Follow the actual execution path; do not rely solely on README files or comments.

## 1. Findings from the exported data (to be explained, not assumed to be bugs)

The 2026-11-21 export contains 97 deployment rows, 82 fields, 42 scored deployments (37 standard, 5 smoke), and 55 rows with no exported tier. Nine are active; 88 unreachable. Archived records may be excluded. All 37 standard runs report identical scored-item counts:

| Axis | Smoke | Standard |
|---|---:|---:|
| Knowledge | 5 | 100 |
| Reasoning | 5 | 100 |
| Math | 5 | 100 |
| Coding | 5 | 40 |
| Tool calling | 5 | 125 |
| Instruction | 5 | 50 |
| Structured | 5 | 30 |
| Long context | 5 | 57 |
| Total | 40 | 602 |

- Exported Borda points equal 42 minus axis rank; the overall score sums six quality axes. Three of the top four deployments are smoke-only. Recomputing Borda over standard deployments alone moves GLM 5.3 Flash Spark from rank 4 to rank 1 and Qwen Flash Next Q2 Prism NoThink from tied 11 to tied 8.
- Among 37 standard entries: reasoning median 96 (23 score >=95); math median 96 (27 score >=95); tool-calling scores range only 52–67.2, median 61.6; coding median 32.5, range 0–65; structured output is 100 for 35/37; long context is 100 for 23/37.
- Qwen Flash Next Q2 Prism NoThink: knowledge 87, reasoning 98, math 97, coding 25, tools 64, instruction 84, structured 100, long context 71.9 (41/57 if binary). Configured context 262144. Wall time 4779.4 s, 485 correct, 9.85 s/correct, TTFT 834.40 ms, prefill 196.77 t/s, no exported output TPS. Arena screenshot displays 61.85 output t/s for this deployment during one example.
- Two Qwen 3.6 35B name-pairs (ordinary and gmu38) have coding 0 versus 52.5 with NoThink; instruction 46/42 versus 84/80 respectively. Standard run durations are 8136.5/8287.5 s versus 1773.9/1858.0 s. This may be genuine behavior, response truncation, parser issues, or differences in deployment/configuration.
- Output TPS is missing for eight standard deployments, including several Strata/Trellis deployments and the Q2 Prism deployment (exact set below). Prefill and TTFT are populated for all 37. Two Qwen4 Exp Side deployments show TTFT 174315.28 and 83706.81 ms, prefill 0.74 and 1.53 t/s. Speed index/reference are missing for all 37. Seconds per correct equals suite wall time divided by n_correct within rounding, and n_correct is consistent with the sum of all eight axes' item scores (including gates).
- Visible UI already has Wilson CIs, smoke/standard/thorough tiers, six radar axes, structured/long-context gates, Borda tables, model history/archive, model discovery and overrides, Arena streaming, live benchmark console, and an unfinished Pi-based coding-agent bench.

Treat these as observations from an export, not proof of underlying causes. Exact missing-TPS names: `qwen38-flash-strata-trellis-ud-iq4-xs-nothink`, `qwen38-flash-next-q2-prism-nothink`, `qwen38-flash-strata-trellis-ud-iq4-xs`, `qwen38-flash-strata-trellis`, `deepseek-v4.1-flash-trellis`, `qwen38-flash-q4-strata-trellis`, `or-deepseek-v4-flash`, `glm-maya-s24-trellis`.

## 2. Map the architecture and persistence

Provide a compact annotated source tree (exclude build output, dependencies and generated assets). Trace from a user selecting a tier through job creation, inference request, response/event handling, per-item scoring, storage, aggregation, Compare and CSV export. List relevant modules and data entities; include schema and key relationships for deployments, models, benchmark definitions, runs, item observations, scores and metadata.

- Are model identities distinct from endpoint aliases, model artifact/quantization, runtime, host and inference settings? Can an alias be reused for changed weights/hardware without creating a new identity?
- What versions of datasets, task selection, prompts, evaluator, runtime and configuration are persisted per run or axis? How are stale/invalid axes detected? What constitutes a compatible run?
- Explain best-tier selection, combining multiple runs, whether a tier can mix axes from different dates, archive/delete behavior, and the exact scope of export. Is the 55-row unscored cohort actually untested or excluded by stale/version rules? Can older incompatible runs still be accessed?
- Does the database retain exact sent prompts/messages/tools, raw streamed and assembled responses (including reasoning fields), extracted answers, expected targets, item IDs, finish reasons, token usage, timings, error category, retries and effective inference parameters? What is retained versus only shown in live logs? Can existing raw outputs be rescored without inference?
- Identify configuration, discovery and API dependencies on LiteLLM or its metadata conventions. LLManifold is the existing replacement gateway. Inspect whether BenchBase supports a generic OpenAI-compatible endpoint and how manual overrides/metadata are handled.

## 3. Dataset and evaluator audit (highest priority)

For every current benchmark (format, tinyMMLU, tinyARC, tinyGSM8K, LiveCodeBench, BFCL, IFEval, JSON schema, needle/context), supply a row with upstream source/revision, license if known, dataset split, item IDs/order, tier sample counts, selection method/seed, exact evaluation mode, scorer version and output fields. Locate actual data assets and evaluator entry points. Explain any custom approximations.

### tinyBenchmarks
- Are the official ICML 2024 selected items, weights and estimator(s) used, or are scores plain percentages? Identify exact package, data revision, weighting and formula; distinguish raw subset accuracy from full-benchmark estimate.
- Do knowledge/reasoning use choice log-likelihood, answer-letter generation, or another method? Do these match the selected upstream protocol? Specify few-shot examples, system/user templates, answer order, extraction and handling of multiple answers.
- GSM8K: show final-number extraction and normalization, accepted alternate formats, delimiter requirements and how incorrect reasoning with a correct answer is scored. Console `A:` appears to show only numerals despite a show-work prompt: is this raw or extracted?
- How are five-item smoke samples selected? Are they fixed and nested within standard? Are all standard deployments given identical items and order? Explain the Wilson intervals and whether they are based on raw item counts or a weighted estimate. Do not claim that Wilson intervals on a curated subset are automatically uncertainty bounds for the full benchmark.

### LiveCodeBench
- Identify release/date window, language, original prompt template and sample selection. Is 40-item scoring pass@1 / execution-based? Describe actual code execution, isolation, resource limits and tests (including hidden tests, if supplied by upstream), extraction, timeouts and failure classification.
- Investigate both Qwen 3.6 35B zero scores with thinking enabled. Are there retained examples to distinguish wrong algorithms, extraction failure, missing/truncated final code, timeouts, or sandbox failures? Do not run models. Provide 2–3 sanitized examples if available, otherwise explain missing evidence.
- How are incomplete solutions, Markdown fenced code, reasoning tags, multiple code blocks and pass@k handled?

### BFCL
- Identify exact BFCL version, task categories and counts, source task IDs, AST/execution/multi-turn scoring, native OpenAI tool calls vs text imitation, parallel calls and no-call tasks. Is score binary per item or partial credit?
- Tool scores occupy a remarkably narrow band. Inspect category-level results, common failures, fixed defaults, supported schema types, parsers and missing fields. Determine whether a category, scoring rule or provider incompatibility creates a practical ceiling. Do not infer a defect merely from clustering.
- Document any invalidity/scoring controls, how controls are constructed and interpreted, and how failed controls affect ranking/export.

### IFEval, schema and long context
- Identify official IFEval verifier usage, strict/loose and prompt/instruction-level metrics, treatment of multiple constraints, and exactly which score is stored.
- Explain schema corpus, validation library, schema variety, constrained decoding vs prompt-only behavior, retries, and distinction between syntactic/schema validity and semantic correctness.
- Show the 57-item long-context test schedule: requested and measured context lengths, needle count/position, tokenization method, distractors, truncation detection, context budget, expected matching, and how tests beyond endpoint capacity are handled. Is the same workload used for each endpoint or scaled to advertised context? The latter would mean scores are not directly equivalent. Explain the 100% gates and the meaning of configured vs actually validated context. Investigate Q2's 71.9% without rerunning.
- Explain basic format check and why/how it participates in tier completion but not the six quality axes.

## 4. Inference execution and performance audit

Trace exact API calls and effective params for bench vs Arena vs agent bench. Identify streaming/nonstreaming differences, token limits, sampling, seed, reasoning mode, chat templates, tool definitions, timeouts, retries, concurrency, request isolation, gateway routing and cache conditions. Do params change by benchmark or deployment? Can they be recovered from history? Are thinking and NoThink true matched variants or merely names?

Provide exact formulas, units, numerator/denominator, start/end timing events, aggregation (mean/median/weighted etc.), and sources of token counts for:
- TTFT (first stream event vs first reasoning token vs first visible text; network/queue time).
- Output TPS, visible output TPS vs total generated tokens, reasoning tokens/time; chunks vs tokens, use of server usage and tokenizer fallback.
- Prefill TPS: actual engine telemetry vs input tokens divided by TTFT or another estimate; distinguish these explicitly.
- Suite wall clock, n_correct, seconds/correct, speed index/baseline, and invalidity rules. Does time include retries, gates, evaluator work and idle time? Does n_correct include all gates? Check whether failed/truncated requests remain in denominator.
- Why are output TPS missing for eight deployments while Arena displays TPS for Q2? Locate the paths and conditions producing missing values. Does lack of usage telemetry, reasoning separation, or another issue explain it? Never silently substitute estimated counts as authoritative server counts.

Look for evidence explaining the two anomalous Qwen4 TTFT values and the much different prefill estimates; inspect saved per-item timing if available. Compare benchmark and Arena implementation paths. A single Arena observation is not a sustained performance measurement.

Describe whether cold/warm prefix and expert caches, background traffic, model loading, thermal throttling and concurrency are controlled or recorded. What information would be needed to reconstruct a fair performance comparison? Suggest narrowly scoped improvements and possible headless AIPerf integration without disrupting the current UI. Do not assume any external framework is installed.

## 5. Aggregation, comparison and uncertainty

Locate score normalization, six radar axes, absolute 0–100 toggle/default scaling, ranking, tie handling, Borda, `n_correct`, gates, baseline speed display, confidence intervals and filters. Explain numerator/denominator, rounding and population for each.

- Why does CSV rank smoke and standard jointly? Is the visible `Include smoke results` switch only a view filter? Are ranking population, selected subset and export scope deliberately different? Demonstrate from code, with a small static test/example if useful (no code changes).
- Identify behavior for missing, stale, invalid, failed or incomplete axes. Are they excluded, treated as zero or replaced by another run? Does Borda penalize missing scores consistently?
- Does export contain global rank, per-filter rank or both? Can scores be recalculated with only standard rows without database changes?
- How are Wilson interval endpoints generated and rounded? Are tests binary and observations independent? Are repeated contexts/schema variants clustered? Does any rank/capability decision account for uncertainty?
- Explain radar scaling and visual comparison; preserve absolute mode and label relative modes. Assess possible ceiling effects and correlated knowledge/reasoning/math axes (exported standard-tier Spearman correlations ~0.69–0.76).
- Identify a nonbreaking path to role-specific profiles, per-axis comparability metadata, and Pareto views, without turning an operational ranking into a purported scientific intelligence metric.

## 6. Agentic coding bench and Arena

Summarize the current Pi integration (not Pine), maturity, task sources/snapshots, agent settings, sandbox/permissions, time/token budgets, tests and scoring. What is reusable? What interface would permit OpenCode and Pi as alternative pinned harnesses while keeping task definitions and scoring independent? Distinguish direct code generation (LiveCodeBench) from agentic coding. Identify current event streaming and whether tool calls, test output and failures can be exposed live.

Summarize Arena multi-model streaming, token/timing derivation, concurrency, image attachments, conversation/state isolation, persistence and ability to replay comparisons. Explain which parts could be reused for a structured live benchmark inspector. Preserve independent streaming and the existing Mantine UI.

## 7. Historical compatibility and migration (non-negotiable)

Do not propose a database reset. Identify existing archives/backups/schema migration history, legacy datasets/runs and what can still be recovered. No writes during audit.

For each issue, classify fix as:
1. Presentation or derived aggregation only (existing observations unchanged).
2. Rescorable from stored raw evidence without inference.
3. New version required (retain original results and version; only comparable within compatible cohorts).
4. New independent metric (legacy measurements remain valid on other axes).

Recommend an append-only/versioned observation and derived-score strategy or show existing support. Specify how old results stay visible, how partial compatibility is represented per axis, what must never be inferred for historical runs, and whether a small paired old/new bridge cohort is feasible. Avoid retroactively applying speculative score corrections. Include backups and migration verification requirements for future implementation.

## 8. Deliverables

Return one concise Markdown report (~3,000–5,000 words plus code excerpts as needed):
- Executive summary: confirmed findings, suspected issues, unknowns, strengths to preserve.
- Architecture, data retention and source file map.
- Benchmark-by-benchmark protocol table and evidence.
- Specific investigation of smoke ranking, BFCL clustering, zero-code thinking variants, missing TPS, long-context gate, and historical data.
- Prioritized recommendations with severity, compatibility class, evidence, tests/acceptance criteria, estimated implementation scope (not time estimates), and relevant files.
- Questions for the owner where evidence is missing.
- Source index with commit, paths, function names and line ranges.

Keep the standard evaluation reasonably runnable in under an hour on representative local models (target, not an unconditional guarantee). Preserve smoke/standard/thorough tiers, live scrolling questions/responses, Arena, radar/Borda views, models/history/CSV export and Mantine UX. Recommend adapters to canonical evaluators where appropriate, not a wholesale rewrite. The eventual goal is empirical deployment capability data usable by LLManifold and an intelligent router. No implementation changes in this pass.
