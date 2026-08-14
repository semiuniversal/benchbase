# Bug: Speed suite reports bogus tok/s on short EOS / fat chat templates

**Severity:** High — radar Speed/Prefill are used as a primary ranker.

**Status:** Fixed (2026-08-11)

**Repro pair:** `qwen3.6-27b-sharp-nothink` vs `qwen3.6-27b-nothink` (same NVFP4 weights; Sharp is a jinja/system-prompt swap only). Standard-tier runs **415** vs **160**.

**Corrected decode (forced-length / long generation):** Sharp **29.0 tok/s** vs stock **34.9 tok/s** — same band, not the radar 11.0. The ~17% gap is leftover noise/template tax, not a 3× engine regression.

## Symptom

Compare radar looked like Sharp was ~3× slower and prefill collapsed. Quality axes were essentially identical.

| Metric | Stock nothink (run 160) | Sharp nothink (run 415) | What actually happened |
|--------|------------------------:|------------------------:|------------------------|
| Radar Speed | 34.9 tok/s | 11.0 tok/s | Decode measured on **11 vs 3** visible tokens. Real Sharp decode: **29.0 tok/s** |
| Radar Prefill | 555 | **7** | TTFT **346 vs 389 ms** — prefill did not collapse |
| `speed:output_token_count2048` | 11 | **3** | Sharp hit EOS after a one-line answer |
| Speed cell wall | ~7 s | ~7 s | Suite still labels the cell `tg=2048` |

TTFT being similar is the tell: the engine is not 80× slower at prefill. The stored `speed:prefill_tps128` of 6.8 is `~1 token / est_ppt`.

## Cause (two stacked bugs)

### 1. Generation length was not enforced

llama-benchy already has `--exact-tg` (`min_tokens` + `ignore_eos`). BenchBase never passed it.

The stream patch then *asked* for a short answer via `_BENCHMARK_SYSTEM` (“short continuation…”). A terse chat template (Sharp) did exactly that: 2–4 tokens, stop. Decode tok/s on two tokens after TTFT is noise.

### 2. Prefill “7” was `adapt_prompt` collapsing `pp` to 1 token

`--adapt-prompt` defaults **on** in llama-benchy 0.3.8. Warmup delta used local **gpt2** vs server `usage.prompt_tokens`, shrinking `current_pp` to 1. `pp_speed = 1 / est_ppt` ≈ 6.8 tok/s, stored as `speed:prefill_tps128`.

## Fix

Forward (new Speed runs):

- Pass `--exact-tg` and `--no-adapt-prompt` from `SpeedRunner`.
- Drop `_BENCHMARK_SYSTEM`. Coherence stays on the fill-in patch.
- Stream patch keeps `min_tokens` / `ignore_eos` after thinking headroom is added to `max_tokens` only.
- Persist gate: if `output_token_count.mean < 32` or `< 0.5 * tg`, store `speed:output_tps*` with `score=None` and `metrics.invalid_reason`. Prefill is nulled when implied prompt tokens `pp_throughput * est_ppt < 8` or `prompt_size <= 8`. TTFT / token-count / completion still persist.

Historical (invalidate only — do not invent tok/s):

- `benchbase rescore-speed` (dry-run default, `--apply`) nulls collapsed `output_tps` / `prefill_tps` and stashes `original_score` + `invalid_reason`. Scorecard already skips `score is None`.
- Comparable Speed/Prefill requires a **Speed-only re-run** when a pair is loaded. Existing cells were 2–15 tokens, not a hidden 2048-token probe; replacing 6.8 with `128/est_ppt` would fake a prompt that never ran.

## Related files

- `src/benchbase/runners/speed.py`
- `src/benchbase/runners/llama_benchy_fix.py`
- `src/benchbase/speed_gate.py`
- `src/benchbase/speed_rescore.py`
- `src/benchbase/cli.py` (`rescore-speed`)
- `tests/test_speed_gate.py`
