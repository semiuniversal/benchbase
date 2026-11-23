# Implementation plan — simplify Addendum A decode TPS (natural completions)

**Goal:** Make **decode tok/s** a practical primary metric without requiring forced-length compliance, LLManifold `allow` lists, or `min_tokens` / `ignore_eos`. Keep the current exact-length bench as an **optional advanced profile**. **No** historic score rewrite, **no** Creative Arena work.

---

## 1. Product / measurement change (one paragraph)

| | **Today (over-applied)** | **Target (primary)** |
| --- | --- | --- |
| Generation | `--exact-tg` on every Standard Speed run | Normal completions: **fixed ~4K prompt**, **`max_tokens` = generous ceiling** (e.g. 512–1024), **no** `min_tokens` / `ignore_eos` |
| Valid replicate | ≥384 generated tokens (75% of forced target) | Enough tokens for stable timing (reuse **≥32** / short-EOS gate on **extreme** junk only), **≥3 of 5** reps with valid **decode-phase timing** and token count |
| Headline invalid | Discard median if too many short natural stops | Publish **median decode TPS** with **`confidence`** / `repetitions_valid`; null only on **errors, timeouts, missing timing**, not natural EOS |
| Integration | LLManifold bench route mandatory | **Any** reachable OpenAI-compatible route; exact-tg check **only** for advanced profile |
| Legacy exact | Same profile id | New profile id **`decode-4k-natural-c1-v1`** (primary); retain **`decode-4k-512-exact-c1-v1`** (optional, Thorough or explicit rerun) |

Historical rows keep their `profile_id` and scores. Scorecard picks **best valid headline** with preference for **natural** on equal tier (documented in scoring, no DB migration).

---

## 2. Smallest code touch map

### A. Speed runner (`src/benchbase/runners/speed.py`)

- **Branch on suite `profile_id` / tier** (from `suite.config_json` + existing `profile_by_pp`):
  - **Standard / Smoke (default):** omit `--exact-tg`; pass `--tg` as **max_tokens ceiling** only (llama-benchy already uses `max_tokens`, not minimum).
  - **Thorough or `decode-4k-512-exact-c1-v1`:** keep `--exact-tg` + current behavior.
- **Remove or narrow** `verify_benchbase_speed_route` preflight: run only when `exact_tg` profile active (or behind setting `speed_require_manifold_allow: false` default).
- Persist `profile_id` / `method` / `forcing: natural|exact` in decode result `metrics_json`.
- Log line: replace “Re-run after exact-tg fix” with confidence-aware message when applicable.

**~30–50 lines** changed; no new runner class.

### B. Suite config (`src/benchbase/db/session.py` seed + existing DB via config)

- Default Speed suite for Standard:
  - `profile_id`: `decode-4k-natural-c1-v1`
  - `profile_by_pp`: `{4096: "decode-4k-natural-c1-v1", 32768: "decode-32k-natural-c1-v1"}` (optional mirror 32K natural later; can defer 32K to phase 2)
  - `tg`: `[512]` stays as **ceiling**, not forced count
- Add parallel **exact** profile entries for Thorough `passes` or a `speed_profiles.exact` flag consumed by runner.

**Additive JSON** in suite config; Alembic not required.

### C. Aggregation & gates (`src/benchbase/decode_tps.py`, `src/benchbase/speed_gate.py`)

- Add `median_decode_headline_natural()` (or parameterize `median_decode_headline`):
  - Valid if: replicate has **decode TPS > 0**, **generated_n ≥ MIN_STABLE`** (e.g. 32, align with `MIN_DECODE_TOKENS`), **timing present**; optional flag `reasoning_tokens_hidden` unchanged.
  - **Do not** call `replicate_meets_profile(..., 384)`.
  - Require **≥3 valid** of 5 for `repetitions_valid`; if 1–2 valid → set score + `invalid_reason: low_confidence` **or** publish with `confidence: "low"` (pick one; recommend **publish + qualifier** for primary metric UX).
- **`visible_decode_tps` / `gate_decode_replicates`:** stop using **0.95×tg** as headline gate for natural profile; keep strict gate **only** when `profile_id` ends with `-exact-`.
- `speed_gate.evaluate_speed_result`: same profile-aware branch.

**~80 lines** across two modules; most churn in conditions + tests.

### D. Scoring & export (`src/benchbase/scoring.py`, `export_scorecard_csv.py`)

- `_extract_speed`: when multiple `speed:decode_tps*` rows exist, prefer **`decode_tps` with `profile_id` natural** and `invalid_reason` null for standard cohort; fall back to exact profile, then legacy `output_tps`.
- Expose optional fields: `decode_confidence` (`high|low`), `decode_forcing` (`natural|exact`).
- **No** rescoring of old runs.

**~25 lines.**

### E. UI (`frontend/src/components/comparison/DecodeSpeedCard.tsx`, `speedFormat.ts`, `ComparePage.tsx`)

- Show qualifier from profile: **“4K prompt · natural stop · single request”** vs exact string.
- Badge: **Measured** when `decode_tps != null` even if `confidence === low` (secondary line: “2/5 long runs”).
- **PARTIAL** only when no usable `decode_tps` (errors / no timing), not when naturally short.
- Radar: unchanged hub logic; uses headline when present.

**~40 lines.**

### F. Docs / ops (defer heavy MCP churn)

- Short addendum **A.1** or replace §3 profile table in `DECODE_TPS_FRICTION.md` + pointer in HANDOFF.
- Mark `SPEED_DECODE_ROUTE_PROCEDURE.md` **“exact profile only”**; stop implying Standard requires `allow`.
- Keep `verify-speed-routes` CLI for advanced / debugging.

**Docs only in this pass** (unless you want doc commit with code).

### G. Tests

| File | Change |
| --- | --- |
| `tests/test_decode_tps.py` | Natural median: 2/5 reps at 150 tok → scored; 0/5 at 3 tok → null |
| `tests/test_speed_runs_profile.py` | Standard tier expects **no** `--exact-tg` in argv mock |
| `tests/test_manifold_speed_route.py` | Unchanged; optional skip when natural runner |
| `tests/test_speed_gate.py` (if any) | Profile-aware branches |

**No new test harness.**

### H. Explicitly out of scope

- Creative Arena, WP7, adapters, Borda formula changes.
- LiteLLM sticky probe removal (still useful after rare exact runs).
- Forced-length **rescore** of history.
- New benchmark framework or non–llama-benchy driver.

---

## 3. Implementation order (single PR, ~半 day)

1. **decode_tps + speed_gate** — natural aggregation + profile switch (tests green).
2. **session.py** suite config + runner argv branch (remove default exact-tg).
3. **scoring** preference for natural profile.
4. **UI** qualifiers + confidence display.
5. **Disable** default manifold preflight (exact only).
6. **Doc** addendum paragraph + HANDOFF one-liner.

**Verification:** rerun Speed on Trellis nothink, Prism, GLM without LLManifold allow; expect **Measured** decode with natural stops. Run one **Thorough** or flagged exact run to confirm old path still gates at 384.

---

## 4. Risk / compatibility

| Risk | Mitigation |
| --- | --- |
| Cross-seat comparison noisier (natural length varies) | Median of 5 + report `generated_token_count` distribution in metrics |
| Thinking models shorter visible phase | Keep **engine-native** generated token timing (already in patch) |
| Two profile ids in flight | Scorecard rule + CSV `decode_tps_profile` column already exists |
| User expects 4K→512 label | Update copy to “4K prompt · up to 512” |

---

## 5. Decision needed before coding

1. **Low confidence:** publish tok/s with badge vs null + reason (recommend **publish**).
2. **32K thorough:** natural profile now or follow-up.
3. **Exact profile tier:** Thorough only vs “Speed (exact)” axis-only button.

---

**Status (2026-11-23):** Implemented — natural primary profile, Speed (exact) suite, confidence UI, fallback measurement chain, tests green.

**Next step:** rebuild `benchbase:local` and re-run Standard Speed on fleet seats (no LLManifold allow required).