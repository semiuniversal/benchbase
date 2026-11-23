# BenchBase vNext — Addendum A: Definitive Decode Tokens/Second

**Revision:** 1.0 · 22 November 2026  
**Audience:** Cursor coding agent implementing the existing BenchBase application  
**Status:** implementation-ready, deliberately narrow  
**Parent:** `BenchBase_vNext_Specification_v1.2.md` — chiefly §8 *Inference performance and token accounting*, WP2, and the portions of WP5/WP6 that display performance  
**Basis:** `BenchBase_Cursor_Methodology_Audit_Response.md` (static audit at commit `8543f6fd82c9133d3ab4aa954dd28b5665e80a82`); reconcile with current code before editing

> **Instruction to Cursor:** Treat this as a bounded implementation task that can be completed in the current session. Do **not** implement Creative Arena, OpenCode integration, new benchmark families, new ranking formulas, or a new benchmarking framework. Don't replan the entire vNext project. Inspect the relevant code, implement the smallest safe change set, add tests, and report what is and is not actually measured. If current vNext implementation already differs from the audit, adapt to it; do not blindly overwrite recent work.

---

## 1. Product decision

**A prominently displayed, defensible, reproducible single-user decode tokens/second (TPS) value is a first-class product requirement.** Users should find it immediately on the model summary, model details, and Compare. It's a primary sorting and selection metric, not a dimension of the six-axis quality Borda score.

Show a concise headline in this form:

**`57.8 tok/s · 4K→512 · single request`**

For an unavailable measurement, show **`— tok/s`** with a short reason and a **Run speed test** affordance where already supported. Do not substitute other throughput measures or zero.

The headline is intentionally *not* an all-purpose performance index. It answers: *How fast does this deployment generate tokens after generation starts, at the named input/output size, one request at a time?*

Primary baseline profile: **4,096 input tokens → target 512 generated tokens, concurrency 1, one warm-up and five measured repetitions**. Existing valid results may be reused if the protocol and measurement are genuinely equivalent and provenance can be established. A profile ID and revision must accompany every measurement.

## 2. Precise measurement semantics

### 2.1 The primary metric — decode TPS

Measure token generation **after the first generated token**. Exclude request setup, queueing, model load, and prompt prefill entirely.

When the engine exposes exact generated-token events or authoritative decode-phase timing:

```text
N = number of genuinely generated model tokens in the measured output phase
T_first = time the first generated token completed
T_last  = time the last generated token completed

Decode TPS = (N - 1) / (T_last - T_first)
```

Require `N >= 2`, positive duration and a sufficiently long measured generation to avoid jitter dominating the figure. If engine-native statistics provide generated tokens and **decode-phase duration**, use those documented semantics directly; don't subtract first token again when the engine has already excluded it. Preserve the source's counting and timing conventions.

**Thinking mode does not alter this definition.** Generated reasoning tokens are tokens. When they are available in the engine's authoritative timing/counting data, count them in decode throughput just like answer tokens. Thinking may increase **time until the answer is visible** and total tokens consumed, but that waiting time must not be charged to decode TPS. Thinking can still affect actual throughput through different kernels, output distributions, context growth or execution paths; don't promise identical numerical TPS for thinking on and off.

### 2.2 Distinguish clocks and populations

| Field | Meaning | Must not be confused with |
|---|---|---|
| `decode_tps` | Generated tokens per second during the post-first-token decode phase, using matched token and phase timing | End-to-end tokens divided by wall time |
| `ttft_generated_ms` | Request start to **first model-generated token**, if observable | First visible answer when reasoning is hidden |
| `time_to_visible_answer_ms` | Request start to first user-visible answer token | True TTFT |
| `prefill_tps` | Prompt processing throughput from an engine-reported/validated prefill measurement | Input tokens divided by TTFT without accounting for queueing |
| `visible_decode_tps` | Rate for visible answer text only, where accurately tokenized and timed | Full decode TPS when thinking is hidden |
| `end_to_end_tps` | Total generated tokens / entire request wall duration, if measured | Primary headline decode TPS |
| `system_tps` | Aggregate throughput across simultaneous requests | Single-user TPS |

If an endpoint silently generates unexposed reasoning tokens, its final `completion_tokens` may include tokens not present in the streamed visible text. **Do not divide that count by the visible-answer streaming interval**. That combines incompatible numerator and denominator and yields a fictitious rate.

Similarly, SSE chunks are transport packets, **not tokens**. One chunk may hold zero, one or multiple tokens, or only part of a text fragment. Count neither chunks nor characters nor words as genuine model tokens.

### 2.3 Valid ways to obtain the headline

Use the strongest method actually available for each measurement:

1. **Engine-native benchmark timing and token counts (preferred).** Existing `llama-benchy` is the initial default. Preserve raw output, its exact timing semantics, validation/gate results and test profile. The engine's documented, matched token population and decode-phase duration may be used for `decode_tps`.
2. **Verified provider-native per-request decode timing/token counts.** Accept only if their semantics match the primary definition. Persist backend/version and an explicit method string.
3. **Client-observed token-level events** only when the API genuinely emits one timestampable generated token per event *and* includes hidden reasoning where appropriate. Ordinary OpenAI-compatible text chunks usually do not satisfy this condition.
4. **Visible-output timing/tokenization** may provide a distinct *visible* throughput estimate; label its method. Never silently promote it to the canonical `decode_tps` in the presence of hidden generation, batched chunks, uncertain tokenization or other mismatches.

If none is available, `decode_tps = null`; explain why. A truthful blank is superior to a precise-looking false number.

**Important current-code concern:** The audited `src/benchbase/runners/speed.py` uses a llama-benchy patch that strips thinking and reports visible output tokens divided by an output-phase interval. Inspect its actual raw data and calculations before calling it full generated-token `decode_tps`. When it only measures *visible* output, preserve that as `visible_decode_tps` or a clearly labeled legacy field, and obtain canonical generated TPS from validated engine data if possible. Don't silently change the meaning of existing `output_tps` columns.

## 3. Reproducible speed profile

### Required v1 profile

| Setting | `decode-4k-512-c1-v1` |
|---|---|
| Input target | 4,096 model tokens |
| Generated output target | 512 model tokens |
| Concurrency | One in-flight request |
| Warm-up | One separate unscored request after model load |
| Measured repetitions | Five independent requests |
| Headline aggregation | **Median of valid per-request decode TPS values** (not aggregate tokens divided by aggregate time) |
| Generation | Deterministic or documented settings, usually temperature 0 |
| Thinking | Record effective state; don't mix modes in one measured cohort |
| Cache behavior | Explicitly documented and stable (control prefix-cache reuse and warmup effects) |
| Endpoint | Record direct versus LLManifold/gateway route |
| Resource contention | Quiescent/single-request when feasible; record known contention, do not silently claim an isolated system |

Generate or select an **actual token-length-controlled prompt** when the exact tokenizer is accessible; otherwise record measured/estimated input length and method. If output forcing is supported, document EOS behavior; if not, capture actual output lengths and reject prematurely terminated repetitions against a stated minimum (initial suggestion: **384 generated tokens**, subject to existing gates). Don't pressure models to produce pathological output just to satisfy a target; a fixed-length speed benchmark and a natural-completion workload are different profiles.

Use explicit invalidity reasons, including `insufficient_output_tokens`, `missing_generated_token_count`, `missing_decode_phase_timing`, `token_timing_population_mismatch`, `invalid_time_interval`, `reasoning_tokens_hidden`, `engine_reported_invalid`, `interrupted`, `timeout`, `model_error`, and `mixed_profile`. The precise enumeration can fit the existing conventions, but users must see intelligible messages.

Do **not** fabricate values for historical eight-or-so deployments whose previous `output_tps` was gated out; the audit says the detailed `speed_gate.py` reason must be consulted. Existing speed results from other profiles must stay available but must not become a `decode-4k-512-c1-v1` headline by reinterpretation.

### Optional subsequent profile (not a blocker)

Add `decode-32k-512-c1-v1` later, using the same definition, to show context-length slowdown. Other profile variants and AIPerf integration belong to WP6, **not this narrow task**.

## 4. Data shape and compatibility

Use existing `Run`, `Result`, raw llama-benchy output and current results/export infrastructure wherever practical. Do not propose a database rewrite solely for this feature. If a small schema migration is needed, make it additive and reversible where feasible.

Minimum normalized data for each speed result:

```json
{
  "profile_id": "decode-4k-512-c1-v1",
  "deployment_revision_id": "<existing-or-new-identifier>",
  "route": "gateway",
  "thinking_mode": "off",
  "metric": "decode_tps",
  "value": 57.8,
  "unit": "generated_tokens_per_second",
  "method": "engine_native_decode_timing",
  "source": "llama-benchy",
  "source_version": "<observed-version>",
  "repetitions_requested": 5,
  "repetitions_valid": 5,
  "aggregation": "median",
  "valid": true,
  "invalid_reason": null,
  "observations": [
    {
      "prompt_tokens": 4096,
      "generated_tokens": 512,
      "decode_phase_ms": 8840,
      "decode_tps": 57.8,
      "valid": true,
      "invalid_reason": null
    }
  ]
}
```

**Illustrative schema and values only.** Adapt field names to the current repository and avoid duplicating existing deployment/protocol metadata. A real implementation must retain *all five* raw observations (the example shows one for brevity), unscored warm-up metadata, and gate decisions. The top-level median must be computed from real per-request results, not inserted manually. If deployment revisions are not yet implemented because WP3 is incomplete, use the best available immutable run/configuration identity, label the gap, and avoid blocking WP2 on a major WP3 migration.

For every measured rate, persist or link to: protocol revision, token population (generated-all vs visible-only), timing method, first/last generated token timestamps *if truly available*, exact/estimated counts, actual output length, backend name/version, quantization/deployment identity if available, run status, and invalid reason. Separate environment/session details from the numeric scalar.

**History rule:** Do not rewrite, overwrite, delete or backfill legacy measurements unless exact derivation from preserved raw evidence is proven. Expose legacy method/provenance as `legacy`, `visible-only`, `unknown`, or another honest label. Null remains null. Keep old CSV columns for compatibility; add fields/columns rather than silently changing their semantics. Preserve quality scores and Borda unchanged.

## 5. UI: make TPS obvious

Implement minimally in the existing React/Mantine UX; respect its current layout and reusable components.

**Required:**

- Model list/scorecard: prominent **`57.8 tok/s`**, qualifier **`4K→512 · single request`** and a compact method/validity indicator. Make TPS sortable, treating unavailable values as missing rather than zero.
- Model details: expand to see tested profile, median and **five measured samples**, input/output counts, TTFT, prefill where valid, backend, thinking state, direct/gateway route and the measurement source. Offer an explanation for null and a link to the original run evidence.
- Compare: a clearly labeled **absolute tok/s** column/field for models with compatible profiles. No normalization to a 0–100 quality scale. Show incomparable profiles as such, not as ranked equals.
- Export: include numeric TPS, profile, method, validity, route, thinking, sample count and reason for missing/invalid; preserve existing exports.
- Arena: **remove/rename the existing `chunk_count / elapsed` TPS label immediately.** Display `— tok/s` unless a genuinely valid token-rate source is available; a separate `chunks/s` diagnostic may remain if explicitly labeled. Do not block the canonical Speed runner on solving live Arena throughput.

Keep TTFT and time to first visible answer separate wherever both exist. Do not print “0 tok/s” for absent or invalid evidence. No misleading colored success badge for an estimate.

## 6. Existing code paths to inspect first

From Cursor's previous read-only audit; line numbers may have changed:

| Area | Known starting point | Intended narrow change |
|---|---|---|
| Speed runner | `src/benchbase/runners/speed.py` | Confirm llama-benchy timing semantics, token population, gating, normalized samples |
| Speed validity | `src/benchbase/speed_gate.py` | Reuse/clarify replica gates and invalid reasons |
| Arena SSE | `src/benchbase/api/routes/arena.py` | Stop reporting chunk rate as TPS |
| Scorecard aggregation | `src/benchbase/scoring.py` | Project truthful speed fields without altering six-axis scoring |
| API and CSV | Existing scorecard and `exportScorecardCsv.ts` | Expose profile/method/validity and compatible headline |
| Frontend | Existing Models / Compare / Arena components | Prominent, consistently labeled numeric readout |

Current repo may already have vNext modifications, migrations or new performance abstractions. Reconcile with reality rather than rebuilding structures that exist.

## 7. Acceptance tests (must pass before declaring complete)

1. **After-first-token semantics.** Synthetic engine-native trace: 2 s prefill followed by 501 generated tokens over 10 s between first and last → **50.0 tok/s**, not approximately 41.7 tok/s. Increase prefill to 20 s while holding decode events fixed: TPS stays **50.0**; TTFT changes.
2. **Thinking semantics.** Inject 2,000 generated reasoning tokens followed by 500 visible answer tokens, with authoritative matched phase timing. All-generated decode includes both; increasing the time before the first generated token does not reduce TPS. Time to first visible answer changes as expected. If only visible answer events plus aggregate completion usage are available, full decode TPS is **null**, not a plausible estimate.
3. **Chunk invariance.** Deliver the same generated text using 1, 5, and 100 SSE chunks. The result must never derive canonical generated TPS from the chunk count. Where no true token-level timestamps exist, Arena must show unavailable/appropriate estimate instead of numeric measured TPS.
4. **Invalid samples.** Early EOS, zero/one generated token, no matched timing, stream timeout and mismatched usage populations are rejected or classified with explicit reasons; no NaN/infinity/zero masquerades as valid.
5. **Median behavior.** Five valid samples `[40, 55, 50, 48, 52]` → headline **50 tok/s**. One invalid sample must be excluded with sample count shown; if below the configured minimum valid count, headline is unavailable rather than presented as fully measured. Choose and document a minimum (recommended **3 of 5**); never hide the reduction in confidence.
6. **Historical integrity.** Import/restore a representative old DB snapshot. Historical quality scores, raw speed results, gated nulls, and smoke/standard ranking remain unchanged. Legacy values do not silently become canonical `decode_tps`.
7. **Interface/export.** Model list, detail, Compare, Arena and CSV/API use consistent labels and reasons. Missing data sorts after measured values and never affects Borda.
8. **No production side effects.** Tests use fake endpoints or checked-in fixtures. No production benchmarks, external inference charges, auto-downloads, database wipes or new workload launches during development without owner approval.

## 8. Definition of done / requested Cursor response

Deliver a small, reviewable implementation with:

1. Files changed, brief architecture/measurement summary, and precise definitions for the displayed metrics.
2. Evidence that the `llama-benchy` extraction really matches the canonical generated-token decode definition, **or** a clearly explained separation into `visible_decode_tps` versus authoritative generated `decode_tps` with unknown values honestly retained. Don't claim success if this isn't established.
3. Unit/integration tests and their results, including synthetic thinking and chunking cases; any blocked tests should be named.
4. Database migration/backward-compatibility report, export schema notes, and known limitations.
5. Screenshot or description of where the headline appears, if UI rendering verification is available.
6. Explicit statement of what remains deferred to WP6 (AIPerf, concurrency load tests, long-context performance profiles, general performance adapter redesign).

**Stop after this task.** Do not proceed to Creative Arena, agent execution, benchmark canonicalization, or infrastructure changes until the owner chooses the next work package.
