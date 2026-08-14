# Bug: Quality (and llama.cpp Speed) starve thinking-on seats

**Severity:** High — BenchBase’s job is a capability gauge: *which model should I actually run on this hardware?* A thinking-on GGUF is a normal deployable seat. The first Nail Standard radar answered that question with zeros.

**Status:** Partial fix (2026-08-11). Quality headroom + visible extract deployed. Nail quality re-run queued (runs **542–550**). Speed on llama.cpp still not comparable. Do **not** re-run the nothink fleet.

**Repro seat:** `qwen3.6-35b-nail` (peculiar-ragdoll Nail Qwen3.6-35B-A3B UD-Q6_K_XL via llama.cpp; chat template forces thinking). Model id **53**. First Standard pass runs **505–514**. Control: frozen vLLM `qwen3.6-35b-nothink` (same 35B family, thinking off).

## Product failure

Operators compare *deployable seats*, not sanitized clones. Nail *is* thinking-on GGUF. Frozen 35B *is* NVFP4 nothink on vLLM. If the harness cannot extract an answer from the first, BenchBase cannot pick a winner. That is the whole product.

The fleet nothink radars remain valid **among seats served that way**. They do not excuse a thinking seat scoring 0 because the runner asked for 64 tokens.

## Symptom

First Nail Standard (`505–513`) vs frozen 35B nothink:

| Axis | Nail 505–513 | Frozen 35B nothink | Nail raw |
|------|-------------:|-------------------:|----------|
| Smoke | **28** | 100 | think dump, format checks fail |
| Knowledge | **0** | 82–84 | `max_tokens=64`; content is “Thinking Process: 1. Analyze…” |
| Reasoning | **3** | 98 | same; one item lucked a trailing `D` |
| Math | 60 | 89–91 | 512 tokens sometimes enough to finish think + number |
| Coding | 20 | 37–47 | 1200 tokens; think tax still hurts |
| Tool calling | 32 | 57–60 | 256 tokens |
| IFEval | 26 | 68–74 | 256 tokens |
| Structured | **0** | 100 | 256 tokens of think; never valid JSON |
| NIAH | **0** | 100 | `max_tokens=64` |

Speed run **514** completed but decode was **gated blank**:

| Field | Nail 514 |
|-------|----------|
| `speed:output_tps2048` | `score=None` — `short EOS: output_token_count.mean=67.7 < 0.5 * tg=2048` |
| Visible tokens (3 passes) | 46 / 29 / 128 |
| Think tokens | 1510 / 493 / 1522 (mean 1175) |
| TTFT / think_ms | 23 s (same number) |
| Prefill | 1667 tok/s (kept) |
| JSON `original_score` | ~51 tok/s on 68 visible tokens — **not** comparable to frozen 35B **75.6** on ~2048 |

After the quality patch, Smoke re-run **542** scored **96** (was 28). That is the first signal the extract was the bug, not the weights.

## Cause

### 1. Visible `max_tokens` is also the think budget

`chat_once` sent the axis cap as the API cap:

| Axis | Cap |
|------|----:|
| Knowledge / Reasoning / NIAH | 64 |
| Smoke / Structured / IFEval / tools | 256 |
| Math | 512 |
| Coding | 1200 |

A thinking-on model spends that on `<think>` / prose CoT. Extract-then-compare then sees no letter, no JSON, no needle. Nothink seats emit `B` and EOS in a handful of tokens, so the same cap looked “fine” for months.

Speed already added `_THINKING_HEADROOM = 2048` on `max_tokens` and `--exact-tg` (`min_tokens` + `ignore_eos`). Quality did not.

### 2. Scorer treated thinking as the answer

```python
content = msg.get("content") or msg.get("reasoning_content") or ""
```

Empty `content` fell through to `reasoning_content`. llama.cpp/Nail often put the chain-of-thought **in `content`** as “Thinking Process:” / “Here's a thinking process:” with no `<think>` tags. `extract_mc_letter` then either:

- saw many A–D letters in the option restatement → `unparseable`, or
- never reached “The answer is B” because generation stopped at 64 tokens.

Structured `json.loads` the think preamble → 0.

### 3. llama.cpp ignores the Speed length hammer

`--exact-tg` works on **vLLM** (`min_tokens` / `ignore_eos`). Nail’s llama.cpp server finished think (~1175 tokens) and a terse answer (~68 visible) and stopped. Gate correctly refused to rank 67.7 tokens as `tg=2048`. This is the same family as `doc/bug-speed-short-eos.md`, plus a runtime that does not honor the fix.

Sparkrun GGUF recipes use `runtime: llama-cpp` (`llama-server`), not vLLM. That is why Nail hit this path at all.

## What this is not

- Not “Nail is a 0 on tinyMMLU.” Same-family frozen 35B nothink is 82–84 on that set.
- Not a reason to re-run 27B / 35B / Holo / 122B nothink. Those models EOS after the letter; extra `max_tokens` does not change their stored scores.
- Not a new suite version. Items and extract rules are unchanged. The runner was not giving thinking seats enough tokens to *reach* extract.

## Fix (quality — deployed)

Forward (new quality runs):

- `chat_once` requests `max_tokens + THINKING_HEADROOM` (2048). Nothink still EOS early.
- Score `visible_completion(message)` only: strip `<think>…</think>` / open `<think>`, strip leading “Thinking Process:” / “Here's a thinking process:” blocks, **never** fall back to `reasoning_content`.
- Tests in `tests/test_scoring_remediation.py`.

Historical:

- Leave nothink radars alone.
- Discard Nail **505–513** as invalid (harness-starved). Keep them as the broken-harness record.
- Re-run **Nail only** for Smoke + quality: **542–550**.

## Still open (Speed on llama.cpp)

Quality headroom does not make Nail Speed comparable.

- vLLM + `--exact-tg` → ~2048 visible tokens, rankable tok/s.
- llama.cpp + terse/thinking template → short visible EOS; gate blanks `output_tps`.

Do not invent tok/s from 68 tokens. Options for a later patch (pick one, don’t silently fill the cell):

1. Backend-specific length force that llama.cpp actually honors, or
2. Serve the Nail *recipe* (template + prompt) on vLLM / NVFP4 so exact-tg works, or
3. Persist think-inclusive decode as a **separate** metric, never as `speed:output_tps2048`.

Until then, Nail Speed stays gated. Prefill/TTFT/think_ms stay informative.

## Related files

- `src/benchbase/runners/quality_common.py` (`THINKING_HEADROOM`, `visible_completion`, `chat_once`)
- `src/benchbase/runners/knowledge.py` (and other axes via `chat_once`)
- `src/benchbase/runners/llama_benchy_fix.py` (Speed headroom; `min_tokens` / `ignore_eos`)
- `src/benchbase/speed_gate.py`
- `doc/bug-speed-short-eos.md` (same gate; vLLM length force)
- `tests/test_scoring_remediation.py`
