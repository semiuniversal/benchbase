# BenchBase audit — 2026-08-15

Snapshot `benchbasemodels20260815_073448.csv`. 20 ranked seats; `executor` / `fast` excluded as LiteLLM role slots.

## Findings

1. **`scorer_error` leaves the denominator.** `score = 100 × passes / |scored|`, so an unfinished item costs nothing while a wrong answer costs everything. Reported scores are upper bounds, and the bias grows with the error count.
2. **The leaderboard is sorted by incompleteness at the top.** Rank 1 ran 89.6% of the suite, rank 2 ran 6.8%, rank 3 ran its coding axis on 23 of 40 items. Rank 4 is the first complete run.
3. **Thinking is not uniformly worse — it's bidirectional**, and the pattern names the bug.
4. **Two rows fail an exact arithmetic identity** that the other 18 satisfy to the decimal.

## 1 · Coding is measuring test length

Every seat above 47.5 took a shortened test. Every seat that ran all 40 items scored 10.0–47.5.

Floor charges dropped items as fails — same treatment `timeout` and `harness_error` already get.

| Seat | Reported | Scored | Dropped | Floor | Range |
|---|---:|---:|---:|---:|---|
| muse-glimmer | 100.0 | 11 | 29 | 27.5 | **27.5 – 100.0** |
| qwen3.8-27b-nothink | 87.0 | 23 | 17 | 50.0 | **50.0 – 87.0** |
| qwen3.5-122b-heretic-nothink | 80.0 | 5 | 35 | 10.0 | **10.0 – 80.0** |
| or-deepseek-v4-flash | 28.9 | 38 | 2 | 27.5 | 27.5 – 28.9 |
| qwen3.6-27b-nothink | 47.5 | 40 | 0 | 47.5 | exact |
| qwen3.6-27b-sharp-nothink | 45.0 | 40 | 0 | 45.0 | exact |
| qwen3.6-35b-nothink | 42.5 | 40 | 0 | 42.5 | exact |
| *(11 more complete runs)* | 37.5 → 10.0 | 40 | 0 | — | exact |

**Consequences.** Muse Glimmer's floor sits below almost every complete run — the coding crown was manufactured by 29 dropped items. qwen3.8-27b's lead *survives* the floor (50.0 vs 47.5 next), so the plan holds, but the margin is 2.5 points inside ±15 intervals, not the 39.5 the dashboard showed.

**External calibration.** Published LiveCodeBench: record **91.6** (Qwen3.7 Max), Qwen3.6-27B **83.9**, Qwen3.6-35B-A3B **80.4**. Two reads:

- No model has ever scored 100. Muse Glimmer's 100.0 was self-refuting before any of the above — worth a hard assertion in the scorer.
- Your axis reads **~36 points below published** across the board (qwen3.6-27b: 47.5 vs 83.9). Separate calibration question from the dropped-item one.

## 2 · Suite coverage, leaderboard order

| Rank | Seat | Coverage | Note |
|---:|---|---:|---|
| 1 | muse-glimmer | 89.6% | coding 11/40, instruction 33/50 |
| 2 | qwen3.5-122b-heretic-nothink | 6.8% | 5 items on every axis |
| 3 | qwen3.8-27b-nothink | 96.9% | coding 23/40 |
| 4 | qwen3.6-27b-sharp-nothink | **100%** | first complete run · 64 GB · 262k ctx · speed 208 |
| 5 | qwen3.6-35b-nothink | 100% | |
| 12 | diffusiongemma-26b | 6.8% | smoke, ranked anyway |
| 20 | qwen3.6-27b | 6.8% | 8 correct of 40 |

Ranks 4–20 are otherwise ≥98.5%.

## 3 · Think − nothink, three clean pairs

Same base model, same tier.

| Axis | nemotron-3.5-lightning.35 | nemotron-3.5-lightning | glm-4.7-flash |
|---|---:|---:|---:|
| knowledge | +14.0 | +13.0 | +15.0 |
| reasoning | +6.0 | +5.0 | +8.0 |
| math | 0.0 | 0.0 | +7.0 |
| tool calling | +1.3 | +1.3 | +1.3 |
| **structured** | **0.0** | **0.0** | **0.0** |
| coding | −2.5 | −7.5 | −12.5 |
| instruction | −36.0 | −30.0 | −6.0 |
| long context | −30.0 | −25.0 | −35.0 |

**Structured is the control.** It's the only axis under constrained decoding and the only one that doesn't move. Everything that collapses is free-form output where format and completeness are graded. A model does not gain 14 points of knowledge while losing 36 of instruction-following — that's truncation or think-token leakage, not capability loss.

Corroborating: `ttft_ms == think_ms` to two decimals for all 8 thinking seats, so TTFT measures prefill on nothink seats and the entire reasoning phase on thinking ones. (Also: `or-deepseek-v4-flash` logs 651 think tokens — the speed baseline is itself a thinking model.)

Note this cuts *against* thinking being harmful: published figures suggest reasoning should be worth tens of points on coding for this family. Your harness measures it going down. That gap is the size of the defect.

## 4 · The plate/axis identity

`n_correct == Σ(score × n_items)` over the eight quality axes holds **exactly for 18 of 20 seats**. Two violations:

| Seat | Plate `n_correct` | Axes sum | Max possible | Effect |
|---|---:|---:|---:|---|
| qwen3.5-122b-heretic-nothink | 475 | 37 | **40** | impossible — halves of the row are from different sittings |
| qwen3.6-35b-nail | 124 | 442 | 577 | wrong by −318 |

- **122b**: either the plate is stale and `sec/correct` ≈ 83 (speed index ~15, not 191), or the axes are stale and the quality scores are fiction. Not both.
- **nail**: `sec/correct` should be 3859.5 ÷ 442 ≈ 8.7 → speed index ≈ **141**. Currently blank, `speed_invalid_reason` empty, while 31.12 s/correct still publishes and the seat holds rank 8.

## Fixes

| # | Change | Catches |
|---|---|---|
| 1 | Retry `scorer_error` with bounded retries; on final failure count as a **fail**, matching `harness_error` | items vanishing inside an axis |
| 2 | Assert `n_correct == Σ(score × n_items)` at persist; refuse the row on mismatch | plate and axes drifting apart |
| 3 | Assert coding score < 100 | impossible LiveCodeBench results |
| 4 | Completeness gate before Borda — don't rank an axis below a coverage threshold | 5-item smoke runs landing at #2 |
| 5 | Emit planned vs scored `n` per axis; split `ttft_ms` from `think_ms` | silent truncation; two quantities in one column |

Regression test for #1: on any completed standard run, `n_items` should equal the planned count on every axis, and the coverage chart becomes a flat wall of 100%.

## Next step

Re-run **qwen3.8-27b's coding axis to the full 40**. That single number decides which model gets the coding box, and it's the cheapest measurement on the list.
