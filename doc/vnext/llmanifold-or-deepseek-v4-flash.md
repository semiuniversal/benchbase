# LLManifold route — `or-deepseek-v4-flash` (measurement reference)

**Status:** operator reference · 2026-11-23  
**Consumers:** BenchBase on revenant, Compare work-clock index, Speed decode baseline  
**Upstream:** OpenRouter (not local vLLM)

---

## Role in BenchBase

| Field | Value |
|--------|--------|
| **Advertised model id** | `or-deepseek-v4-flash` |
| **BenchBase `Model.name`** | `or-deepseek-v4-flash` (active) |
| **`work_clock_reference_model`** | `or-deepseek-v4-flash` ([`config/settings.yaml`](../../config/settings.yaml)) |
| **Purpose** | **Primary comparison reference** for work-clock speed index and canonical **decode tok/s** cohort; other seats are ranked relative to this deployment when a valid decode headline exists |
| **Agentic instrument (separate)** | OpenRouter `deepseek/deepseek-v4-flash-0731` — see [`doc/agentic-instrument.md`](../agentic-instrument.md) |

This route is the **basis for measurement** semantics: new local seats should match **passthrough** behavior defined here so Speed results are comparable.

---

## Upstream (OpenRouter)

| Item | Value |
|------|--------|
| **Provider** | OpenRouter OpenAI-compatible API |
| **Base URL** | `https://openrouter.ai/api/v1` |
| **Model slug** | `deepseek/deepseek-v4-flash-0731` |
| **Secret** | `OPENROUTER_API_KEY` on revenant (not in git) |
| **LiteLLM / gateway path** | `http://revenant.jackalope-bicolor.ts.net:20004` → route name `or-deepseek-v4-flash` |

LLManifold must proxy chat completions to OpenRouter with **per-request** body fields preserved (below), not a sticky global `min_tokens` on the quality route.

---

## BenchBase Speed profile (Addendum A) — what this route must support

Canonical profile: **`decode-4k-512-c1-v1`**

| Setting | Value |
|---------|--------|
| Input (prefill) target | **4096** tokens (`pp=4096` only on Standard/Smoke) |
| Generation target | **512** tokens (`tg=512`) |
| Concurrency | **1** |
| Measured replicates | **5** (Standard tier) |
| llama-benchy | `--exact-tg` |
| API fields per replicate | `max_tokens` ≥ 512 (+ thinking headroom in client), **`min_tokens`: 512**, **`ignore_eos`: true** |
| Valid replicate | ≥ **384** generated tokens counted in engine-native decode phase |
| Headline | **Median** of ≥ **3** valid replicates → `speed:decode_tps512` |

Implementation: [`src/benchbase/runners/llama_benchy_fix.py`](../../src/benchbase/runners/llama_benchy_fix.py), [`src/benchbase/runners/speed.py`](../../src/benchbase/runners/speed.py).

**After any Speed bench on the fleet:** restart LiteLLM or verify sticky `min_tokens` is cleared on **chat** routes (workspace rule). Sticky forced length breaks quality benchmarks and small `max_tokens` probes.

---

## Known behavior (audit / legacy runs)

- **Thinking model:** DeepSeek Flash via this route may emit substantial **reasoning** before visible text; decode headline uses **generated** tokens when timing is available ([`doc/benchbase-audit.md`](../benchbase-audit.md) — ~651 think tokens on old 2048 profile).
- **Historical Speed rows** on this seat used legacy **`tg=2048`**; many runs **gated** (`short EOS`). Re-run **Standard → Speed only** on the current image to populate `decode_tps`.
- **Do not** treat legacy `output_tps2048` as the headline; UI uses `decode_tps` per Addendum A.

---

## LLManifold entry (paste / reconcile)

Use as the **authoritative** route spec when registering or updating on revenant LLManifold:

```yaml
# LLManifold — measurement reference route (BenchBase vNext)
route_id: or-deepseek-v4-flash
advertised_name: or-deepseek-v4-flash
description: >
  OpenRouter DeepSeek V4 Flash — BenchBase work-clock reference and decode-4k-512-c1-v1
  measurement basis. Must pass min_tokens/ignore_eos for Speed exact-tg; no sticky min_tokens on chat.

upstream:
  kind: openrouter
  base_url: https://openrouter.ai/api/v1
  model: deepseek/deepseek-v4-flash-0731
  api_key_env: OPENROUTER_API_KEY

benchbase:
  measurement_reference: true
  work_clock_reference: true
  decode_profile: decode-4k-512-c1-v1
  thinking: true  # record effective mode in runs; do not mix cohorts

proxy:
  # Required for comparable Speed (llama-benchy --exact-tg)
  pass_through_chat_body:
    - min_tokens
    - ignore_eos
    - max_tokens
  # Do NOT set persistent route-level min_tokens or ignore_eos for normal chat
  sticky_generation_forbidden: true

availability:
  advertise: true
  park: false
```

---

## Checklist after route change

1. `POST /api/settings/litellm-probe?model=or-deepseek-v4-flash` — must **not** report sticky `min_tokens`.
2. BenchBase: **Standard → Speed only** on `or-deepseek-v4-flash`.
3. Confirm `speed:decode_tps512` score present and `decode_invalid_reason` null (or documented gate).
4. Compare: reference seat shows **Measured** decode badge, not **Gated** (UI may still say “Unavailable” until UX fix — metric is valid).

---

## Template for other seats (e.g. Prism local quant)

Mirror **proxy.passthrough** and **no sticky min_tokens**. Local vLLM must honor the same `min_tokens` / `ignore_eos` (or backend equivalent). Failure mode: generations stop at ~100–200 tokens → `insufficient_valid_replicates` (see qwen3.6 IQ2 prism-nothink, 2026-11-23).