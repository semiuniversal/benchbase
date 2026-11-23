"""Canonical decode TPS profile and aggregation (Addendum A)."""

from __future__ import annotations

import statistics
from typing import Any


def _metric_mean(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        mean = value.get("mean")
        if mean is not None:
            return float(mean)
        values = value.get("values")
        if values:
            return float(sum(values) / len(values))
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _metric_values(value: Any) -> list[float]:
    if isinstance(value, dict):
        raw = value.get("values")
        if isinstance(raw, list):
            return [float(x) for x in raw if isinstance(x, (int, float))]
    return []

PROFILE_ID = "decode-4k-512-c1-v1"
PROFILE_REVISION = 1
PROFILE_PP = 4096
PROFILE_TG = 512
PROFILE_MIN_GENERATED = 384  # 0.75 × tg
PROFILE_MIN_VALID_REPS = 3
PROFILE_MEASURED_REPS = 5

DECODE_TPS_PREFIX = "speed:decode_tps"
VISIBLE_DECODE_PREFIX = "speed:visible_decode_tps"
HEADLINE_METHOD = "engine_native_decode_timing"
VISIBLE_METHOD = "visible_output_decode_timing"

INVALID_INSUFFICIENT = "insufficient_output_tokens"
INVALID_FEW_REPLICATES = "insufficient_valid_replicates"
INVALID_MIXED = "mixed_profile"


def generated_decode_from_request(
    *,
    reasoning_ts: list[float],
    output_ts: list[float],
    first_reasoning_ts: float | None,
    first_output_ts: float | None,
    reasoning_tokens: int,
    output_tokens: int,
) -> tuple[float | None, int, float | None, str | None]:
    """Decode TPS over all generated tokens (reasoning + visible output)."""
    total_n = int(reasoning_tokens) + int(output_tokens)
    if reasoning_tokens > 0 and not reasoning_ts:
        return None, total_n, None, "reasoning_tokens_hidden"
    if total_n < 2:
        return None, total_n, None, "missing_generated_token_count"

    first_gen: float | None = None
    if first_reasoning_ts is not None and first_output_ts is not None:
        first_gen = min(first_reasoning_ts, first_output_ts)
    elif first_reasoning_ts is not None:
        first_gen = first_reasoning_ts
    else:
        first_gen = first_output_ts

    if first_gen is None:
        return None, total_n, None, "missing_decode_phase_timing"

    last_ts: float | None = None
    if reasoning_ts:
        last_ts = max(reasoning_ts)
    if output_ts:
        last_ts = max(output_ts[-1], last_ts or output_ts[-1])
    if last_ts is None:
        return None, total_n, None, "missing_decode_phase_timing"

    duration = last_ts - first_gen
    if duration <= 0:
        return None, total_n, None, "invalid_time_interval"

    decode_tps = (total_n - 1) / duration
    return decode_tps, total_n, duration * 1000.0, None


def replicate_meets_profile(token_count: float, tg: float = PROFILE_TG) -> bool:
    return token_count >= PROFILE_MIN_GENERATED and token_count >= 0.75 * tg


def median_decode_headline(
    token_metric: Any,
    tps_metric: Any,
    *,
    tg: float = PROFILE_TG,
    min_valid: int = PROFILE_MIN_VALID_REPS,
) -> tuple[float | None, str | None, int, int]:
    """Return (median decode tps, invalid_reason, valid_count, total_count)."""
    tokens = _metric_values(token_metric)
    tps_vals = _metric_values(tps_metric)
    total = max(len(tokens), len(tps_vals))
    if not tokens and not tps_vals:
        mean_n = _metric_mean(token_metric)
        if mean_n is not None and not replicate_meets_profile(mean_n, tg):
            return None, f"{INVALID_INSUFFICIENT}: n={mean_n:.0f} < {PROFILE_MIN_GENERATED}", 0, total
        return _metric_mean(tps_metric), None, 0, total

    valid_tps: list[float] = []
    for i, n in enumerate(tokens):
        if not replicate_meets_profile(n, tg):
            continue
        if i >= len(tps_vals) or tps_vals[i] <= 0:
            continue
        valid_tps.append(tps_vals[i])

    if len(valid_tps) < min_valid:
        return (
            None,
            f"{INVALID_FEW_REPLICATES}: {len(valid_tps)} valid of {len(tokens)} "
            f"(need ≥{min_valid} with n ≥ {PROFILE_MIN_GENERATED})",
            len(valid_tps),
            len(tokens),
        )
    return round(statistics.median(valid_tps), 2), None, len(valid_tps), len(tokens)


def profile_qualifier(profile_id: str | None = None) -> str:
    if profile_id == PROFILE_ID:
        return "4K→512 · single request"
    return "speed profile"