# Speed decode tok/s — repeatable route procedure

**Audience:** any Cursor session (BenchBase *or* LLManifold), human operator, MCP agents.  
**Goal:** every Standard Speed run receives `min_tokens` + `ignore_eos` on the wire so Addendum A decode can pass the gate.

---

## The contract (read this first)

| Side | Rule |
| --- | --- |
| **BenchBase** | Sends OpenAI `model: <Model.name>` on every Speed request (`--exact-tg`). |
| **LLManifold** | Strips `min_tokens` / `ignore_eos` unless that **exact route name** lists them in `allow`. |
| **Together** | **`Model.name` must equal the LLManifold route name** that has `allow: [min_tokens, ignore_eos]`. |

Creating `my-seat-bench` without renaming (or without updating BenchBase) **does not work**. Splitting routes without step 5 in the LLManifold runbook is the usual failure.

Upstream (vLLM, OpenRouter, Strata Poly, llama.cpp) must still honor forwarded forcing — LLManifold only stops stripping.

---

## Role split

| Session | Repo / MCP | Delivers |
| --- | --- | --- |
| **LLManifold** | `/home/semiuniversal/llmanifold`, MCP `http://127.0.0.1:20004/mcp` | Route table: `clients`, `allow`, chat vs bench split |
| **BenchBase** | `benchbase`, port 8099 | `Model.name`, Speed runner, gates, Compare UI |

Cross-repo task list for MCP: **`llmanifold/doc/CURSOR_TASK_BENCHBASE_SPEED_ROUTES.md`** (mechanics). **This file** is the ordered procedure both sides follow.

---

## Phase 0 — Before any new seat

1. Pick the **canonical route name** = what will appear as **BenchBase `Model.name`** (e.g. `glm-5.3-flash-spark`).
2. Decide chat alias name (e.g. `glm-5.3-flash-spark-chat`) if Hermes/Open WebUI share the same weights.

---

## Phase 1 — BenchBase (add or confirm seat)

1. **Discover** / add model; **`name`** must match the LLManifold **bench** route name you will publish.
2. `endpoint_url` → inference gateway (revenant: `http://…:20004`, no `/v1` required in YAML).
3. Do **not** point Speed at a chat-only route name.

---

## Phase 2 — LLManifold (publish bench route)

Required fields on the **bench** route whose `name` == `Model.name`:

```yaml
clients: [benchbase]
allow: [min_tokens, ignore_eos]
proxy_read_seconds: 60
# fixed: never min_tokens / ignore_eos here
```

**After splitting chat vs bench:**

1. Bench route **keeps** `Model.name` (preferred), **or**
2. Patch BenchBase `Model.name` to the `-bench` alias.

See **Part B finish (step 5)** in `llmanifold/doc/CURSOR_TASK_BENCHBASE_SPEED_ROUTES.md`.

Chat route: `clients: [hermes, openwebui]` (no `benchbase`), `allow: []`.

---

## Phase 3 — Verify (mandatory gate)

### From BenchBase host

```bash
cd /home/semiuniversal/benchbase
uv run benchbase verify-speed-routes          # all active models
uv run benchbase verify-speed-routes -m glm-5.3-flash-spark
```

Or API: `GET /api/models/{id}/speed-route-check`  
Or MCP: `verify_speed_route` with `model_name=…`

**Pass:** `ok: true`. **Fail:** read `fix_hint` — do not start Speed until pass.

### Manual LLManifold probe (optional)

```bash
curl -sS -X POST "http://127.0.0.1:20004/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"<Model.name>","messages":[{"role":"user","content":"count 1-200"}],
       "max_tokens":512,"min_tokens":512,"ignore_eos":true,"stream":false}' \
  | jq '.usage.completion_tokens'
```

Expect **≥ 384** (target 512). If LLManifold passes but BenchBase fails, fix **upstream runtime**.

---

## Phase 4 — Speed benchmark

1. **Speed axis only** (or full tier if new seat).
2. Speed runner **aborts early** if Phase 3 would fail (log line cites this doc).
3. Headline: `speed:decode_tps512`, need **≥3/5** reps with **≥384** generated tokens.

---

## Phase 5 — Compare / release

1. Nameplate: **Measured** decode, not **Unavailable** (gated).
2. Radar decode spoke uses **Settings baseline** at hub (not a fixed vendor).
3. Rebuild `benchbase:local` if UI changed.

---

## Failure encyclopedia

| Symptom | Cause | Fix |
| --- | --- | --- |
| Prefill + TTFT ok, **— tok/s**, `0 valid of 5` | exact-tg stripped | Phase 2–3; name mismatch `-bench` |
| `1 valid of 5` after “fix” | Still on chat route or weak upstream | Verify curl; check run log `--model` |
| `2 valid of 5` on Prism | Strata/upstream, not LLManifold | Upstream forcing; rerun |
| Probe 512 ok, Sherlock bench short | Prompt/stream path | Seat owner; not strip |
| Speed abort before llama-benchy | Phase 3 failed | `verify-speed-routes` |

---

## Files

| File | Purpose |
| --- | --- |
| This doc | Single procedure |
| `llmanifold/doc/CURSOR_TASK_BENCHBASE_SPEED_ROUTES.md` | Copy-paste MCP JSON |
| `llmanifold/doc/benchbase-speed-routes.md` | Policy |
| `src/benchbase/manifold_speed_route.py` | Automated check |
| `doc/vnext/llmanifold-or-deepseek-v4-flash.md` | Reference seat |