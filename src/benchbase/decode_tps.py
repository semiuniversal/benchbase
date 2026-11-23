"""Canonical decode TPS profile and aggregation (Addendum A + natural primary)."""

from __future__ import annotations

import statistics
from typing import Any, Literal

Confidence = Literal["high", "low"]


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


# Primary natural-output profile (Standard Speed).
PROFILE_ID_NATURAL = "decode-4k-natural-c1-v1"
# Optional forced-length diagnostic (Speed exact suite).
PROFILE_ID_EXACT = "decode-4k-512-exact-c1-v1"
# Historical exact id (pre-natural migration); treated as exact, not headline-preferred.
PROFILE_ID = "decode-4k-512-c1-v1"
PROFILE_ID_32K = "decode-32k-512-c1-v1"

EXACT_PROFILE_IDS = frozenset({PROFILE_ID, PROFILE_ID_EXACT, PROFILE_ID_32K})
NATURAL_PROFILE_IDS = frozenset({PROFILE_ID_NATURAL})

PROFILE_REVISION = 2
PROFILE_PP = 4096
PROFILE_PP_32K = 32768
PROFILE_TG = 512
PROFILE_MIN_GENERATED = 384  # 0.75 × tg (exact profile only)
PROFILE_MIN_VALID_REPS = 3
PROFILE_MEASURED_REPS = 5
NATURAL_MIN_GENERATED = 32
NATURAL_PREFERRED_VALID = 3

DECODE_TPS_PREFIX = "speed:decode_tps"
VISIBLE_DECODE_PREFIX = "speed:visible_decode_tps"
HEADLINE_METHOD = "engine_native_decode_timing"
VISIBLE_METHOD = "visible_output_decode_timing"
STREAMING_METHOD = "client_streaming_token_timing"

INVALID_INSUFFICIENT = "insufficient_output_tokens"
INVALID_FEW_REPLICATES = "insufficient_valid_replicates"
INVALID_MIXED = "mixed_profile"
INVALID_NO_MEASUREMENT = "measurement_failure"


def is_exact_profile(profile_id: str | None) -> bool:
    return profile_id in EXACT_PROFILE_IDS


def is_natural_profile(profile_id: str | None) -> bool:
    if profile_id in NATURAL_PROFILE_IDS:
        return True
    if profile_id is None:
        return True
    return profile_id not in EXACT_PROFILE_IDS


def suite_forcing(suite_config: dict[str, Any] | None, active_profile: str | None) -> str:
    cfg = suite_config or {}
    if cfg.get("forcing") == "exact":
        return "exact"
    if active_profile in EXACT_PROFILE_IDS:
        return "exact"
    return "natural"


def confidence_from_valid_count(valid_n: int) -> Confidence | None:
    if valid_n >= NATURAL_PREFERRED_VALID:
        return "high"
    if valid_n >= 1:
        return "low"
    return None


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


def replicate_meets_natural(token_count: float) -> bool:
    return token_count >= NATURAL_MIN_GENERATED


def median_decode_headline(
    token_metric: Any,
    tps_metric: Any,
    *,
    tg: float = PROFILE_TG,
    min_valid: int = PROFILE_MIN_VALID_REPS,
    forcing: str = "exact",
) -> tuple[float | None, str | None, int, int, Confidence | None]:
    """Return (median decode tps, failure_reason, valid_count, total_count, confidence)."""
    if forcing == "natural":
        return median_decode_headline_natural(token_metric, tps_metric, min_preferred=min_valid)

    tokens = _metric_values(token_metric)
    tps_vals = _metric_values(tps_metric)
    total = max(len(tokens), len(tps_vals))
    if not tokens and not tps_vals:
        mean_n = _metric_mean(token_metric)
        if mean_n is not None and not replicate_meets_profile(mean_n, tg):
            return (
                None,
                f"{INVALID_INSUFFICIENT}: n={mean_n:.0f} < {PROFILE_MIN_GENERATED}",
                0,
                total,
                None,
            )
        mean_tps = _metric_mean(tps_metric)
        conf = confidence_from_valid_count(1 if mean_tps is not None else 0)
        return mean_tps, None, 0, total, conf

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
            confidence_from_valid_count(len(valid_tps)),
        )
    return (
        round(statistics.median(valid_tps), 2),
        None,
        len(valid_tps),
        len(tokens),
        "high",
    )


def median_decode_headline_natural(
    token_metric: Any,
    tps_metric: Any,
    *,
    min_preferred: int = NATURAL_PREFERRED_VALID,
) -> tuple[float | None, str | None, int, int, Confidence | None]:
    """Publish median whenever ≥1 replicate has trustworthy timing and token count."""
    tokens = _metric_values(token_metric)
    tps_vals = _metric_values(tps_metric)
    total = max(len(tokens), len(tps_vals))

    valid_tps: list[float] = []
    for i, n in enumerate(tokens):
        if not replicate_meets_natural(n):
            continue
        if i >= len(tps_vals) or tps_vals[i] <= 0:
            continue
        valid_tps.append(tps_vals[i])

    if not valid_tps and tokens:
        # Single aggregate without per-rep split — only if mean length passes floor.
        mean_n = _metric_mean(token_metric)
        mean_tps = _metric_mean(tps_metric)
        if mean_n is not None and replicate_meets_natural(mean_n) and mean_tps and mean_tps > 0:
            return round(float(mean_tps), 2), None, 0, total, "low"

    if not valid_tps:
        return None, INVALID_NO_MEASUREMENT, 0, total, None

    score = round(statistics.median(valid_tps), 2)
    conf = confidence_from_valid_count(len(valid_tps))
    _ = min_preferred
    return score, None, len(valid_tps), total, conf


def select_decode_measurement(
    thinking: dict[str, Any],
    bm: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str, str]:
    """Pick best available throughput metrics: generated → visible decode → streaming."""
    pairs: list[tuple[str, str, str, str]] = [
        (
            "generated_decode_tg_throughput",
            "generated_token_count",
            HEADLINE_METHOD,
            "llama-benchy",
        ),
        (
            "output_decode_tg_throughput",
            "output_token_count",
            VISIBLE_METHOD,
            "llama-benchy",
        ),
        (
            "output_tg_throughput",
            "output_token_count",
            STREAMING_METHOD,
            "llama-benchy",
        ),
    ]
    for tps_key, tok_key, method, source in pairs:
        tps = thinking.get(tps_key) or bm.get(tps_key)
        tok = thinking.get(tok_key) or bm.get(tok_key)
        if isinstance(tps, dict) and tps.get("values"):
            return tps, tok, method, source
        if isinstance(tps, dict) and tps.get("mean") is not None and _metric_mean(tok):
            return tps, tok, method, source
    return None, None, HEADLINE_METHOD, "llama-benchy"


def profile_qualifier(profile_id: str | None = None, forcing: str | None = None) -> str:
    force = forcing or ("exact" if is_exact_profile(profile_id) else "natural")
    if profile_id == PROFILE_ID_NATURAL or (force == "natural" and profile_id != PROFILE_ID_EXACT):
        return "4K prompt · natural stop · concurrency 1"
    if profile_id == PROFILE_ID_EXACT or profile_id == PROFILE_ID:
        return "4K→512 forced · single request (exact)"
    if profile_id == PROFILE_ID_32K:
        return "32K→512 · single request (exact)"
    return "speed profile"