# BenchBase — Scoring Observations, Failure Theory, and Remediation

**Status:** Draft for review
**Date:** 2026-08-08
**Companion to:** `benchbase-spec.md` (v2 spec). This document diagnoses the observed score saturation, lays out the theory of how deterministic scorers fail, and specifies remediation. Its normative content (§5–§7) is intended to merge into the spec as §6.2 and additional acceptance criteria.

---

## 1. Observation

Two 35B-parameter MoE models evaluated on the v2 suites return 100% (or near) on Knowledge, Reasoning, Math, Coding, and Long context. Tool calling alone shows differentiation. Structured output and Instruction following differentiate for one model.

## 2. Why this is not a real result

A benchmark score is bounded by the hardest items in the set. The tiny/sampled sets were chosen specifically to retain hard items (IRT anchors are selected for discriminative power, and LiveCodeBench is difficulty-stratified). Reference expectations for a strong 35B-class open model, healthy harness:

| Suite | Plausible range (35B class) | 100% plausible? |
|---|---|---|
| Knowledge (tinyMMLU) | 70–85 (IRT est.) | **No.** Frontier models score ~88–92 on full MMLU; anchor sets contain items most models miss |
| Reasoning (tinyARC-Challenge) | 85–96 | Marginal — high 90s occur; repeated exact 100s across models suspicious |
| Math (tinyGSM8K) | 80–95 | Marginal — same reasoning |
| Coding (LiveCodeBench subset) | 25–60 | **No.** Frontier models do not clear the medium/hard tiers at 100% |
| Tool calling (BFCL subset) | 55–85 | No — and notably, this suite is *not* saturating |
| Instruction following (IFEval subset) | 65–90 | Unlikely |
| Structured output (custom) | 60–95 | Possible for easy schemas; the graded ladder should prevent it |
| Long context (NIAH 8–16k) | 85–100 | **Yes** — simple NIAH is genuinely saturated; this axis alone may legitimately read 100 |

Two independent models both at 100 on five axes has a natural-explanation probability of approximately zero. The tests are not "too easy" (except NIAH); the pipeline is crediting answers it should not.

## 3. The diagnostic asymmetry — why tool calling still works

The suites that saturated are the ones whose scorers can **silently degenerate into always-true**. The tool-calling scorer cannot: AST comparison must parse the model output, resolve a function name, and structurally match arguments — when any of that breaks, it fails *visibly* (score collapses, errors surface). String-side scorers fail *invisibly* (score inflates).

Rule of thumb this yields: **in a multi-suite harness, the suite that still differentiates is the one telling the truth.** Uniform excellence elsewhere is a symptom, not a finding.

## 4. Failure taxonomy

Ordered by prior probability in harnesses of this shape.

### F1. Lenient answer extraction (most likely)

The scorer searches for the gold answer *within* the response rather than extracting *the model's answer* and comparing. Canonical bug: `if correct_letter in response`. Any response that enumerates the options ("A) ... B) ... C) ...") — which chat models do constantly — passes every item. Variants: case-insensitive substring over the whole completion; matching the gold *text* (not letter) when the model restates all options; regex that matches the first letter of the response's restated question.

**Signature:** MC suites saturate; generative suites (math with numeric extraction) saturate only if the extraction is similarly greedy (e.g., "gold number appears anywhere in the CoT" — GSM8K chains frequently mention intermediate values equal to the answer).

### F2. Answer leakage into the prompt

The prompt builder concatenates dataset fields that include the gold answer (many HF datasets carry `answer`, `target`, and `choices` in one record), or few-shot exemplars are drawn from the same pool being scored, or a chat template includes a previous turn containing the answer.

**Signature:** genuinely high scores with plausible-looking transcripts — the model *is* answering correctly, because it was told the answer. Detectable only by reading the rendered prompt, not the response.

### F3. Pass-by-default control flow

The checker treats "no exception" or "no explicit failure" as success: a `try/except` that swallows comparison errors and falls through to `passed = True`; a sandbox harness that returns exit code 0 when the test file itself failed to load; a timeout path that records success.

**Signature:** exact 100s including on items where the response is visibly wrong or empty. Fastest to confirm: does an *empty* response pass?

### F4. Wrong data

Train split loaded instead of test; a placeholder/stub item file (e.g., the 5-item Smoke set wired into the Standard tier); LiveCodeBench config pointing at the old HumanEval items; dataset version with `answer` prepended to `question` by a bad join.

**Signature:** suite runtime much shorter than the tier estimate; item counts in the run record not matching the suite manifest.

### F5. Contamination (real, but not this)

Models trained on benchmark data genuinely ace it. This inflates MC and older suites by points, not to uniform 100s, and cannot explain LiveCodeBench-at-100 if the subset is date-filtered. Treat as the residual explanation once F1–F4 are excluded.

## 5. Diagnostic procedure (do in order; ~15 minutes)

1. **Read ten transcripts** from Coding and ten from Knowledge (per-item storage, spec §5, exists for exactly this). For each: what did the model literally output, and what did the scorer credit? F1 and F3 are usually visible within the first three.
2. **Read two rendered prompts** (the exact string sent to the endpoint) from each saturated suite. F2 is only visible here.
3. **Check run item counts** against the suite manifest (F4), and compare suite wall time against the tier estimate.
4. **Run the negative controls** (§6). Any control scoring above its bound localizes the broken scorer without reading anything.

## 6. Remediation: negative controls (normative — spec §6.2)

Three synthetic "models" ship with BenchBase and run against every suite version. They cost minutes and no GPU.

| Control | Behavior | Must score |
|---|---|---|
| `null` | Returns empty string for every request | 0 on every suite (0 tool calls credited, 0 schemas validated, 0 code passes) |
| `random` | MC: uniform random valid letter. Generative: fixed nonsense string. Tools: syntactically valid call to a randomly chosen declared function with empty args | MC suites: chance ± Wilson 95% bound (25% on 4-choice). All generative/executable suites: ≤ 5. Tool calling: below the irrelevance-category base rate |
| `echo` | Repeats the prompt (including any options) back verbatim | 0 on every suite — **this is the F1 killer**: substring-style scorers credit `echo` at ~100% |

Enforcement rules:

- Controls run automatically on: first install, every suite-version bump, and every scorer code change (CI). Results stored like normal runs, flagged `control: true`, excluded from Compare.
- **Gate:** if any control violates its bound, the affected suite is marked `scorer-invalid`; real results for that suite display a warning state and are excluded from Borda and radar until controls pass. The app does not silently show numbers it has proven it cannot trust.
- A fourth, optional control — a deliberately weak real model (~1B) — provides a soft ordering check: it must rank below any healthy 35B on every axis except by legitimate tie at NIAH. Advisory, not gating (small models occasionally have real spiky skills).

## 7. Remediation: scorer hardening (normative)

- **Extraction before comparison, always.** Every scorer extracts the model's committed answer (letter, final number, code block, JSON object, tool call) into a typed value, then compares. If extraction fails, the item is scored **incorrect with reason `unparseable`** — never skipped, never defaulted. Unparseable rate is reported per run; >20% unparseable triggers a run-level warning (usually a template problem, which is Smoke's job to catch).
- **MC scoring:** extract exactly one letter via anchored patterns (end-of-response preferred: "answer is X", final standalone letter). Multiple distinct letters extracted → `unparseable`, incorrect.
- **Math:** extract the final number after the last reasoning delimiter (e.g., GSM8K `####` convention or last number in the final line), not any-number-anywhere.
- **Prompt audit fixture:** for each suite, one golden-file test asserts the rendered prompt for a known item contains the question and options and does **not** contain the gold answer string. Catches F2 at build time.
- **Sandbox honesty:** code execution distinguishes {tests passed, tests failed, harness error, timeout}; only the first scores as pass. Harness errors surface in the run record, not as either pass or fail.
- **No silent exception paths in scorers.** A scorer exception marks the item `scorer-error` (excluded from the proportion, counted and displayed); it never resolves to pass *or* fail silently.

## 8. Additional acceptance criteria (merge into spec §11)

13. `null`, `random`, and `echo` controls score within bounds on every suite; violating suites enter `scorer-invalid` and are excluded from Compare/Borda until cleared.
14. `echo` specifically scores 0 on all MC suites.
15. An empty model response on any item scores incorrect-`unparseable`, never pass, never skip.
16. Per-run display includes unparseable and scorer-error counts; >20% unparseable shows a run-level warning.
17. Golden-file prompt tests exist per suite and fail if the gold answer appears in a rendered prompt.
18. Re-running the two saturated 35B MoEs after remediation yields Knowledge/Coding scores within the plausible ranges of §2, or else documented cause.

## 9. What "too easy" would actually look like (for contrast)

If the tests were merely too easy: scores cluster at 92–99 with per-model variation, CIs overlap but medians differ, harder subsets (LiveCodeBench medium/hard, BFCL multi-turn) still separate models, and the `echo` control scores 0. Uniform 100s with a working tool-calling suite is not that picture. After remediation, if NIAH alone still reads 100 — that one is real; the fix there is harder retrieval variants (multi-needle, variable tracking) at 32k+, not scorer work.
