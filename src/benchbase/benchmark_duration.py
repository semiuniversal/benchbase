"""Rough duration estimates for benchmark runs."""

from __future__ import annotations

import math
from typing import Any

# Full dataset sizes (lm-eval test/validation splits used by our task set).
_REASONING_FULL: dict[str, tuple[int, str]] = {
    "gsm8k": (1319, "generative"),
    "arc_easy": (2376, "mc"),
    "hellaswag": (10042, "mc"),
    "mmlu_high_school_mathematics": (270, "mc"),
}

# Conservative per-request seconds (slow local model → fast proxy).
_SEC_GENERATIVE = (25.0, 8.0)
_SEC_MC = (5.0, 1.5)
_SEC_LITE_BENCH = (20.0, 5.0)
_SEC_SPEED_RUN = (60.0, 20.0)  # llama-benchy pass with pp+tg configs


def format_duration_seconds(seconds: float) -> str:
    seconds = max(0, seconds)
    if seconds < 60:
        return f"~{int(seconds)} sec"
    if seconds < 3600:
        return f"~{max(1, int(round(seconds / 60)))} min"
    if seconds < 86400:
        hours = seconds / 3600
        return f"~{hours:.1f} hr" if hours < 10 else f"~{int(round(hours))} hr"
    days = seconds / 86400
    return f"~{days:.1f} days" if days < 10 else f"~{int(round(days))} days"


def format_duration_range(low: float, high: float) -> str:
    low = max(0, low)
    high = max(low, high)
    if high < 90:
        return f"~{int(low)}–{int(high)} sec"
    if high < 5400:
        lo_m = max(1, int(low / 60))
        hi_m = max(lo_m, int(math.ceil(high / 60)))
        return f"~{lo_m}–{hi_m} min"
    if high < 172800:
        lo_h = max(1, int(low / 3600))
        hi_h = max(lo_h, int(math.ceil(high / 3600)))
        if hi_h <= 48:
            return f"~{lo_h}–{hi_h} hr"
        lo_d = low / 86400
        hi_d = high / 86400
        return f"~{lo_d:.1f}–{hi_d:.1f} days"
    lo_d = low / 86400
    hi_d = high / 86400
    return f"~{int(math.floor(lo_d))}–{int(math.ceil(hi_d))} days"


def _reasoning_seconds(meta: dict[str, Any]) -> tuple[float, float, int]:
    if meta.get("full_benchmark"):
        slow = fast = 0.0
        units = 0
        for _name, (count, kind) in _REASONING_FULL.items():
            units += count
            s_slow, s_fast = _SEC_GENERATIVE if kind == "generative" else _SEC_MC
            slow += count * s_slow
            fast += count * s_fast
        return slow, fast, units

    limit = int(meta.get("limit", 50))
    units = limit * 4
    slow = limit * (_SEC_GENERATIVE[0] + 3 * _SEC_MC[0])
    fast = limit * (_SEC_GENERATIVE[1] + 3 * _SEC_MC[1])
    return slow, fast, units


def _coding_seconds(meta: dict[str, Any]) -> tuple[float, float, int]:
    n = int(meta.get("n_samples", 10))
    slow = n * _SEC_LITE_BENCH[0]
    fast = n * _SEC_LITE_BENCH[1]
    return slow, fast, n


def _tool_use_seconds(meta: dict[str, Any]) -> tuple[float, float, int]:
    n = int(meta.get("n_samples", 10))
    # Two tasks by default; truthfulqa capped at 8 in routine unless full.
    if meta.get("full_benchmark"):
        units = n * 2
    else:
        units = n + min(n, 8)
    slow = units * _SEC_LITE_BENCH[0]
    fast = units * _SEC_LITE_BENCH[1]
    return slow, fast, units


def _speed_seconds(meta: dict[str, Any]) -> tuple[float, float, int]:
    runs = int(meta.get("runs", 3))
    units = runs
    slow = runs * _SEC_SPEED_RUN[0]
    fast = runs * _SEC_SPEED_RUN[1]
    return slow, fast, units


def estimate_run_duration(
    runner_class: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Return static duration estimate and work-unit count for a run."""
    calculators = {
        "reasoning": _reasoning_seconds,
        "coding": _coding_seconds,
        "tool_use": _tool_use_seconds,
        "speed": _speed_seconds,
    }
    calc = calculators.get(runner_class)
    if calc is None:
        return {
            "work_units_total": 0,
            "estimate_seconds_low": 0,
            "estimate_seconds_high": 0,
            "estimate_label": "unknown",
        }

    slow, fast, units = calc(metadata)
    return {
        "work_units_total": units,
        "estimate_seconds_low": fast,
        "estimate_seconds_high": slow,
        "estimate_label": format_duration_range(fast, slow),
    }


def estimate_batch_duration(
    queue_size: int,
    settings_batch_limit: int,
    runner_classes: list[str],
) -> dict[str, Any]:
    """Sum per-suite estimates for one model × all suites (batch mode)."""
    from benchbase.benchmark_sampling import build_run_metadata
    from benchbase.config import Settings

    settings = Settings(batch_sample_limit=settings_batch_limit)
    slow_total = 0.0
    fast_total = 0.0
    for rc in runner_classes:
        meta = build_run_metadata("batch", rc, settings)
        est = estimate_run_duration(rc, meta)
        slow_total += est["estimate_seconds_high"]
        fast_total += est["estimate_seconds_low"]

    per_model = format_duration_range(fast_total, slow_total)
    all_models = format_duration_range(fast_total * queue_size, slow_total * queue_size)
    return {
        "estimate_seconds_low": fast_total * queue_size,
        "estimate_seconds_high": slow_total * queue_size,
        "estimate_label": all_models,
        "per_model_label": per_model,
    }
