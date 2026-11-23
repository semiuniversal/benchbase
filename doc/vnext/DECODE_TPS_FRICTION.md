# Decode tok/s — why the current path hurts, and what to do instead

**Status:** problem brief · 2026-11-23  
**Context:** Addendum A (`decode-4k-512-c1-v1`) made single-user decode tok/s a **primary** Compare metric. In production we often get **— tok/s**, **PARTIAL**, and “benchmark succeeded but gate discarded headline.”

---

## What we wanted

One headline number per seat: **how fast does this deployment generate tokens after decode starts**, at a fixed shape (4K prompt → ~512 generated), concurrency 1, reproducible across vendors.

That is the right product question. Users should see it on Models and Compare without reading logs.

---

## What we built

1. **llama-benchy** with `--exact-tg` (`min_tokens` + `ignore_eos` per request).
2. **LLManifold** strips those fields unless the route **allows** them — plus a chat/bench route split so `Model.name` must match the bench route.
3. **Gate:** median over **≥3 of 5** replicates with **≥384** generated tokens; otherwise `decode_tps = null`, UI shows gated / PARTIAL.
4. **Speed preflight** (recent): abort or warn if the route cannot pass exact-tg.

Design goal: **no fake tok/s** from 20-token EOS stops. That goal is sound.

---

## The problem we are actually facing

**The metric is primary, but proving it is owned by three parties none of us fully control:**

| Layer | Failure mode |
| --- | --- |
| **BenchBase** | Sends correct bench; gate withholds headline when data are short. |
| **LLManifold** | Easy to misconfigure (bench alias ≠ `Model.name`); chat routes strip forcing. |
| **Upstream runtime** | vLLM, Strata Poly, Maya, Trellis stacks often **ignore** or **reject** `ignore_eos` / `min_tokens` on real workloads (Sherlock continuation), while a toy “count to 200” curl may work. |

So operators see: **prefill and TTFT look fine**, **axis completed successfully**, log says **Speed gate discarded**, Compare still **PARTIAL**. It feels like BenchBase is broken; often the seat simply never delivered a long enough generation under the bench prompt.

**Concurrent cross-model benchmarking** is unrelated — the pain is **decode comparability**, not the queue.

We also conflate two ideas:

- **Engine throughput** (tokens per second during decode), and  
- **Forced-length compliance** (did the stack actually emit ~512 tokens for this prompt?).

When compliance fails, we discard throughput entirely. For a primary metric, that is **honest** but **operationally brutal**: one flaky replicate or one incompatible engine zeroes the headline users care about.

---

## Why this approach feels “too hard”

1. **Distributed checklist:** LLManifold MCP task, route rename, BenchBase `verify-speed-routes`, Trellis/Prism/Maya seat config — one missed step ⇒ gated forever.  
2. **Bench prompt ≠ health check:** exact-tg may work on a short user message but fail on 4K Sherlock + think templates.  
3. **Binary gate:** 2/5 valid (Prism) is “almost” but UI treats it like 0/5.  
4. **Ops noise:** “Benchmark completed successfully” next to “discarded numeric decode” reads as a bug.  
5. **Heterogeneous engines:** One Addendum profile assumes OpenAI-shaped forcing; Maya errors on `ignore_eos`; Trellis returns 12–215 visible tokens despite allow list.

We are measuring **fleet integration maturity** as much as **hardware speed**.

---

## Better directions (keep honesty, reduce pain)

Pick one or combine; each is a product choice, not a quick patch.

### A. **Tiered headline (recommended direction)**

- **`decode_tps`** — full Addendum pass (≥3/5, ≥384), badge **Measured**.  
- **`decode_tps_provisional`** — median of replicates that cleared a **lower** bar (e.g. ≥2 valid or ≥256 tokens), badge **Provisional** — never Borda, shown gray on radar.  
- **`decode_tps_visible`** — when engine hides reasoning but stream gives visible intervals (already partially in schema).

Users always see *something* for a primary metric, with rank only on **Measured**.

### B. **Seat-native probe (decouple from full Sherlock)**

Short, fixed probe **outside** the quality corpus: same 4K fill, simpler continuation, run once from BenchBase after route verify. Store as `decode_tps` only if profile id matches; fall back to probe-only profile with explicit qualifier.

Reduces “struct/long passed, Speed gate failed” whiplash.

### C. **Upstream capability flag**

LLManifold or BenchBase records `forcing: supported | ignored | rejected` per route from a one-shot test. Speed **skips** exact-tg when unsupported and does **not** claim Addendum A comparability — shows **Engine does not support forced length** instead of running a doomed bench.

### D. **Relax gate with stricter labeling**

e.g. **2 of 5** valid → publish median with `decode_tps_qualifier: "low confidence (2/5)"` and exclude from default cohort. Cheaper than A but still publishes a number.

### E. **Single owner for “speed seat”**

One route name per GPU, always bench-shaped; discovery never points BenchBase at chat routes. Automate rename-on-publish in LLManifold MCP (no human step 5).

---

## What we should not do

- Publish headline tok/s from **short EOS** runs without a label (reverts pre-Addendum lies).  
- Bake `min_tokens` into LiteLLM globals (sticky poison).  
- Drop tok/s from Compare because integration is hard — it **is** a primary metric; the pipeline must get easier or the UX must show graded truth.

---

## Immediate operator reality (today)

Until we change policy:

1. `verify-speed-routes -m <Model.name>` before Speed.  
2. Rerun **Speed only**; need **≥3/5** reps ≥384 in the log.  
3. **PARTIAL** = null headline decode, not necessarily bad quality axes.  
4. If allow is correct but reps stay short → **fix the seat**, not BenchBase scoring.

---

## Suggested next step (when benchmarking quiets)

Decide between **tiered headline (A)** and **capability flag + alternate probe (B+C)** in one spec addendum revision; implement preflight at **batch enqueue** for all tiers that include Speed.

**Related:** [SPEED_DECODE_ROUTE_PROCEDURE.md](SPEED_DECODE_ROUTE_PROCEDURE.md), [BenchBase_vNext_Addendum_Decode_TPS_v1.0.md](../BenchBase_vNext_Addendum_Decode_TPS_v1.0.md).