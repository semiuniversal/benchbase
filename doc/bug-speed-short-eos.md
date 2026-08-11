# Bug: Speed suite reports bogus tok/s on short EOS / fat chat templates

**Severity:** High — radar Speed/Prefill are used as a primary ranker.

**Status:** Open (observed 2026-08-11)

**Repro pair:** `qwen3.6-27b-sharp-nothink` vs `qwen3.6-27b-nothink` (same NVFP4 weights; Sharp is a jinja/system-prompt swap only). Standard-tier runs **415** vs **160**.

## Symptom

Compare radar looks like Sharp is ~3× slower and prefill collapsed. Quality axes are essentially identical.

| Metric | Stock nothink (run 160) | Sharp nothink (run 415) | What actually happened |
|--------|------------------------:|------------------------:|------------------------|
| Radar Speed | 34.9 tok/s | 11.0 tok/s | Decode measured on **11 vs 3** visible tokens |
| Radar Prefill | 555 | **7** | TTFT **346 vs 389 ms** — prefill did not collapse |
| `speed:output_token_count2048` | 11 | **3** | Sharp hit EOS after a one-line answer |
| Speed cell wall | ~7 s | ~7 s | Suite still labels the cell `tg=2048` |

TTFT being similar is the tell: the engine is not 80× slower at prefill. The stored `speed:prefill_tps128` of 6.8 is `~1 token / est_ppt`.

## What the suite claims

Config (`SPEED_SUITE_CONFIG` in `src/benchbase/db/session.py`):

- `pp = [128]`, `tg = [2048]`, 3 runs (standard)

Headline metrics:

- `output_tps` = visible tokens ÷ decode window (`src/benchbase/runners/speed.py`, `llama_benchy_results_patch.py`)
- Prefill = llama-benchy `pp_throughput` (`prompt_tokens / est_ppt`)

Neither number is valid when generation stops after a handful of tokens, or when prompt adaptation shrinks `pp` to 1.

## Cause (two stacked bugs)

### 1. Generation length is not enforced

llama-benchy already has `--exact-tg` (`min_tokens` + `ignore_eos`). BenchBase never passes it (`llama_benchy_runner.py` / `speed.py`).

The stream patch then *asks* for a short answer:

```python
# src/benchbase/runners/llama_benchy_fix.py
_BENCHMARK_SYSTEM = (
    "You are running a latency benchmark. Always respond with a short continuation "
    "of the user message. Output the continuation directly — do not explain your reasoning."
)
```

A terse chat template (Sharp) does exactly that: 2–4 tokens, stop. Decode tok/s on two tokens after TTFT is noise. Stock happened to emit ~11 tokens, so it *looks* 3× faster.

### 2. Prefill “7” is `adapt_prompt` collapsing `pp` to 1 token

`--adapt-prompt` defaults **on** in llama-benchy 0.3.8.

Warmup delta = server `usage.prompt_tokens` − local **gpt2** count of the user string. A force-appended system block (Sharp / froggeric) makes that delta ≥ ~127, then:

```text
current_pp = max(1, 128 - delta_user)  →  1
pp_speed   = 1 / est_ppt               ≈  6.8 tok/s
```

`est_ppt` is still ~148 ms. The result is stored as `speed:prefill_tps128`. TTFT never moved.

gpt2 vs the served tokenizer makes the delta worse even without a fat template.

## Expected

- Prefill uses a real ~128-token *user* prompt, or the result is marked “prompt collapsed”.
- Decode uses a forced length (`min_tokens=tg` / `ignore_eos`), **or** the score is invalid if `output_token_count << tg`.
- Radar must not compare a 3-token cell and an 11-token cell on the same Speed axis.

## Fix (minimal)

1. Pass `--exact-tg` from the speed runner (vLLM honors `min_tokens` + `ignore_eos`).
2. Drop or invert `_BENCHMARK_SYSTEM` for speed — it contradicts a throughput probe.
3. Gate: if `output_token_count.mean < 32` (or `< 0.5 * tg`), do not persist `output_tps` / do not feed the radar; log a warning.
4. `--no-adapt-prompt`, or adapt against the *served* tokenizer, not gpt2.

## Related files

- `src/benchbase/runners/speed.py`
- `src/benchbase/runners/llama_benchy_runner.py`
- `src/benchbase/runners/llama_benchy_fix.py`
- `src/benchbase/runners/llama_benchy_results_patch.py`
- `src/benchbase/db/session.py` (`SPEED_SUITE_CONFIG`)
- `frontend/src/components/comparison/SpeedPlate.tsx`
- `src/benchbase/scoring.py` (`SPEED_PRIMARY_PREFIX`, `SPEED_PREFILL_PREFIX`)
