# Speed index and plate UX — implementation requirements

**Status:** Implemented (2026-08-14)

**Context:** Work clock (`sec_per_correct`, `suite_wall_s`, `n_correct`) is implemented. See `doc/speed-two-metrics.md` and `src/benchbase/work_clock.py`. This doc covers what remains: a readable primary headline, display-time normalization, and forward fixes for secondary tok/s.

**Non-goals:** Re-run Standard/quality fleet. Put speed on the radar. Borda includes speed. Hosted-API baseline. Persist index scores in SQLite.

---

## R1 — Canonical facts vs derived display

| Layer | Stored in DB | Computed when |
|-------|--------------|---------------|
| Run `started_at` / `completed_at` | yes | — |
| Quality `results.metrics_json.successes` | yes | — |
| Speed `speed:output_tps*` (+ gate nulls) | yes | — |
| `sec_per_correct`, `suite_wall_s`, `n_correct` | **no** | scorecard build (`compute_work_clocks_by_model`) |
| **Speed index** (below) | **no** | Compare / Models display |
| **Rank in view** | **no** | Compare display |
| Reference model name | yes | Settings only (`work_clock_reference_model`) |

Changing reference or Compare selection must update the index without rescore or DB writes.

---

## R2 — Speed index (primary headline number)

### Definition

For models A (candidate) and R (reference), same comparable tier:

```
speed_index = round((R.sec_per_correct / A.sec_per_correct) × 100)
```

- Reference sitting = **100**
- Higher is faster (inverse of sec/correct)
- `null` if either side lacks a valid work clock

### Comparability rules (index must be `null` if violated)

1. **Tier:** Both Standard, or both Smoke. Never index Standard vs Smoke.
2. **Contamination:** Either sitting has `invalid_reason` or `work_clock_skip` → no index.
3. **Incomplete quality group:** `quality_complete` false → no index.
4. Optional strict mode (recommended): `abs(n_correct_A - n_correct_R) > 50` → no index (accuracy denominator drift). Document in UI tooltip if enforced.

### Reference model (Settings)

- Field: `work_clock_reference_model: str | null` in `Settings` (`config.py`), `settings.yaml`, settings API.
- UI: Settings page — searchable select of models that have a valid Standard work clock (active or historical); allow empty (= no index, fall back to raw clock display).
- Default when unset: no index; do not auto-pick silently on first load (operator chooses baseline once).

### Display copy

- Headline: **`142`** or **`142%`** (team preference: integer, no decimal)
- Tooltip / subline must name reference: `vs holo-3.1-35b-nothink · 1.8 s/correct`
- If reference unset: headline stays human time (R3), no fake 100

### Color scale

- Remove hardcoded `sec/40` ramp in `SpeedPlate.tsx`.
- Color from **index** when present: map index 50–150 (or 0–200 clamped) to existing blue mix.
- When index absent, dim neutral or scale from sec/correct only among visible Compare rows (client-side min/max), not a magic constant.

---

## R3 — Speed plate layout (Compare + Models)

Component: `frontend/src/components/comparison/SpeedPlate.tsx` (also used on Models list).

**Line 1 (largest):** speed index when reference set and comparable; else formatted work clock (`formatWorkClock`).

**Line 2:** always human-readable facts:
- `{formatWall(suite_wall_s)} · {n_correct} correct`
- append `smoke` badge when `work_clock_tier === "smoke"`
- append `—` + truncated `invalid_reason` when contaminated

**Line 3 (smaller):** `{sec_per_correct}` as **`X.X s/correct`** when index is headline (so raw fact is never hidden).

**Line 4 (smaller still):** `{output_tps} tok/s` + existing prefill / TTFT / think subline.

Requirements:
- Winner obvious at a glance: highest index or lowest sec/correct among visible rows.
- Do not show `/ correct` suffix on the index line (that caused user confusion).
- Smoke sittings: show clock + label; do not imply Standard ranking.

`ComparePage.tsx` caption: mention index is vs configured reference when set.

---

## R4 — Rank in view (Compare only, secondary)

Among models currently rendered on Compare with valid Standard work clocks:

```
rank_in_view = 1 + count(peers with sec_per_correct < this.sec_per_correct)
```

- Display as small badge: **`1st`** / **`2nd`** (ties: `1st tie` same pattern as quality ranks).
- Computed in frontend from scorecard payload for visible model names only.
- Optional: show next to index, not replacing it.
- Smoke and contaminated: no rank badge.

---

## R5 — API / scorecard

`SpeedPlateData` (`frontend/src/api/client.ts`) — add optional fields computed **server-side only for reference index** (not rank in view):

```typescript
work_clock_index?: number | null;      // vs settings reference
work_clock_reference?: string | null;  // model name used
work_clock_reference_sec?: number | null;
```

Implementation: after `compute_work_clocks_by_model`, in `scoring.py` (or small helper in `work_clock.py`):

1. Load `work_clock_reference_model` from settings.
2. Look up reference clock payload.
3. For each model, set index fields per R2 rules.

Do **not** add index to `results` table. Do **not** add migration columns on `runs` for index.

Rank in view stays **frontend-only** (depends on filter set).

---

## R6 — Forward Speed suite (secondary tok/s)

File: `src/benchbase/speed_gate.py`, `src/benchbase/runners/speed.py`, optionally `llama_benchy_results_patch.py`.

Replace mean-length gate with **per-replicate** gate before aggregating:

- For each benchmark replicate, read visible token count from `benchbase_thinking.output_token_count.values[]` or per-request metrics.
- Valid replicate iff `n >= 0.95 * tg` OR `n >= tg - 2` (whichever is stricter/easier to test — pick one, document in gate).
- Aggregate tok/s mean over **valid replicates only**.
- If `< 2` valid replicates: `speed:output_tps*` score `null`, `invalid_reason` set.
- Remove or demote mean-based `decode_invalid_reason` on aggregated mean when per-replicate filtering is in place (keep prefill gate unchanged).

Acceptance: Sharp-style sitting with one 2048 + one 130-token sample does not produce a numeric headline tok/s.

---

## R7 — LiteLLM / quality contamination (ops, not BenchBase code)

Document only: `nemotron-3.5-lightning.35-nothink` Standard group `tier-99b1925bd139` remains in `CONTAMINATED_GROUP_IDS` until clean Standard re-run. Index and rank must stay null for that sitting.

Ensure LiteLLM nothink profiles do **not** inject `min_tokens` / `ignore_eos` globally (Speed warmup `max_tokens=1` regression). BenchBase does not own LiteLLM config; note in operator runbook.

---

## R8 — Tests

Add/update:

| Area | File | Cases |
|------|------|-------|
| Index math | `tests/test_work_clock.py` or new `test_speed_index.py` | 100 when equal; 200 when 2× faster; null tier mismatch; null contaminated |
| Settings round-trip | `tests/test_settings.py` or API test | reference model save/load |
| Per-replicate gate | `tests/test_speed_gate.py` | drop short replicate; null if <2 valid |
| SpeedPlate | optional RTL snapshot | index headline + s/correct subline |

---

## R9 — Documentation

Update `doc/speed-two-metrics.md` § Application changes to point here for index UX.

One paragraph in Settings UI help: index is local baseline, not cloud; change reference in Settings.

---

## R9 — Acceptance checklist

- [ ] Settings saves `work_clock_reference_model`; empty disables index.
- [ ] Compare plate: index headline when reference set; holo ~100, slower seats <100, faster >100.
- [ ] Compare plate: without reference, human time headline; no misleading `/ correct` on index.
- [ ] Smoke labeled; not ranked vs Standard.
- [ ] Contaminated `.35-nothink` Standard shows `—` + reason, no index.
- [ ] tok/s remains visible, smaller than primary.
- [ ] No new persisted score rows for index.
- [ ] Per-replicate Speed gate: 724-style mixed lengths null tok/s or exclude bad samples.

---

## File touch list (expected)

| File | Change |
|------|--------|
| `src/benchbase/config.py` | `work_clock_reference_model` |
| `config/settings.yaml.example` | example field |
| `src/benchbase/api/routes/settings.py` | expose field |
| `src/benchbase/work_clock.py` | `compute_speed_index(ref, candidate)` |
| `src/benchbase/scoring.py` | attach index fields in `_extract_speed` path |
| `src/benchbase/speed_gate.py` | per-replicate decode gate |
| `frontend/src/api/client.ts` | types |
| `frontend/src/components/settings/SettingsPage.tsx` | reference picker |
| `frontend/src/components/comparison/SpeedPlate.tsx` | layout + color |
| `frontend/src/components/comparison/ComparePage.tsx` | rank-in-view badge, caption |
| `tests/*` | R8 |
