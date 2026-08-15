# Speed: work clock first, tok/s second

**Status:** Implemented (2026-08-14)

**Do not re-run the quality fleet.** Standard sittings already have enough timestamps and per-item pass/latency to build the useful number. A full Standard pass is hours to a day.

## Problem

Radar-adjacent Speed is **visible tok/s** from llama-benchy (`tg=2048`, `--exact-tg`). That is a serving probe, not “how fast is this seat at real work.”

It fails apples-to-apples in three ways:

1. **Different distances.** The gate checks *mean* length (`mean(n) ≥ 0.5 × tg`). One short sample (130 or 162 tokens) still votes with two full 2048-token runs. Tok/s then changes every sitting.
2. **Think time is excluded.** Decode tok/s starts after the last think token. Nemotron think looks *faster* than nothink on Speed while wall-clock to a finished Standard is ~5× slower (79 min vs 17 min on the 0.91 sitting).
3. **Forced length is not a job.** `ignore_eos` pads after a natural stop. Quality of the dump is not scored; Quality axes already exist.

Tok/s stays — it is the industry comparison unit and a recipe debugger (`gpu_memory_utilization`, speculator). It must not be the headline.

## Two numbers

| Slot | Name | Meaning | Source |
|------|------|---------|--------|
| **Primary** | **Work clock** | Seconds of scored quality work per correct item | Existing Standard (or Smoke) group; no new generation |
| **Secondary** | **Decode tok/s** | Visible tokens ÷ decode-phase time on a pinned dump | Existing Speed suite (kept, demoted) |

Work clock:

```
suite_wall_s     = Σ (completed_at − started_at) over quality axes
                   (knowledge, reasoning, math, coding, tool_calling,
                    instruction, structured, long_context)
                   exclude Speed; exclude Smoke when the sitting is Standard
n_correct        = Σ results.metrics_json.successes
sec_per_correct  = suite_wall_s / n_correct     if n_correct > 0 else null
```

Use the **sum of axis walls**, not `max(end) − min(start)`. The queue runs two models; a group span includes the other seat.

`Σ result_items.latency_ms` is almost the same number (request wall, think included). Prefer run timestamps so coding sandbox and harness are in the bill — that is real runtime. Muse-Glimmer is the outlier (wall ≫ item latency); still report wall, optionally footnote item-sum.

## Remedy existing scores (rescore, no re-run)

DB check (2026-08-14): 30/30 grouped sittings are complete. Every quality `results` row has `successes`. `result_items.latency_ms` / `passed` are filled except 86 `scorer_error` rows. Speed has no items — ignore it here.

1. Add `benchbase rescore-work-clock` (dry-run default, `--apply`), same pattern as `rescore-speed`.
2. For each `run_group_id` at Standard (else Smoke if that is all the model has), compute `suite_wall_s`, `n_correct`, `sec_per_correct`.
3. Persist on the scorecard (derived; do not invent fake Speed runs). Suggested fields on `SpeedPlateData`:
   - `sec_per_correct` (primary)
   - `suite_wall_s`
   - `n_correct`
   - `output_tps` (secondary, existing)
4. Flag sittings that must not rank:
   - Incomplete groups (already skipped).
   - **Contaminated:** `nemotron-3.5-lightning.35-nothink` Standard (`tier-99b1925bd139`). Sticky LiteLLM `min_tokens: 2048` turned every quality call into a 2048-token dump (knowledge 27 s → 1448 s; long-context 100% → 7.5%). Rescore will replay the bug; mark `invalid_reason` and leave the spoke empty until a clean Standard.
5. `nemotron-3.5-lightning.35` (think) has Smoke only — work clock from Smoke, labeled as such. No invented Standard.

Do **not** rewrite historical `speed:output_tps*` except the existing short-EOS gate (`rescore-speed`). Tok/s stays the stored probe.

## Application changes

Speed is already a **plate**, not a radar spoke (`ComparePage`). Keep it off the radar. Borda stays quality-only.

Primary headline is a **Speed index** (integer %, vs a Settings-chosen local baseline). Raw work clock stays on the plate as a fact. See [`doc/speed-index-requirements.md`](speed-index-requirements.md) (implemented).

## Forward Speed suite (cheap, later)

Keep llama-benchy. Fix the pin so secondary tok/s stops lying:

- Gate **per replicate**, not the mean. Drop samples with `n < 0.95 × tg` (or `tg − 2`). If fewer than 2 valid samples, `output_tps = null`.
- Rank nothing on tok/s. Optional later: headline the dump as wall-to-`tg` among valid samples only.
- Do not put think-on and think-off on one tok/s comparison without showing think wall. Work clock already includes think.

No change to Quality item counts or checkers. Time-to-correct with retries is **agentic T_eff**, already specified — do not duplicate it inside Speed.

## Out of scope

- Re-running Standard for a prettier tok/s.
- Folding Quality into the dump (garbage-under-`ignore_eos` is expected).
- Retry-until-correct as a Speed harness.
- Putting either speed number on the radar.

## Related files

- `src/benchbase/work_clock.py`
- `src/benchbase/scoring.py` (`_extract_speed`)
- `src/benchbase/cli.py` (`rescore-work-clock`)
- `frontend/src/components/comparison/SpeedPlate.tsx`
- `frontend/src/components/models/ModelsPage.tsx`
- `frontend/src/api/client.ts` (`SpeedPlateData`)
- `doc/bug-speed-short-eos.md` (dump-length gate; still valid for secondary tok/s)
