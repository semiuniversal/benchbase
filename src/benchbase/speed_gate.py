"""Invalidate collapsed Speed decode/prefill cells. Do not invent tok/s."""

from __future__ import annotations

import json
import re
from typing import Any

MIN_DECODE_TOKENS = 32
MIN_DECODE_FRACTION_OF_TG = 0.5
MIN_IMPLIED_PROMPT_TOKENS = 8
MIN_PROMPT_SIZE = 8

OUTPUT_TPS_PREFIX = "speed:output_tps"
PREFILL_TPS_PREFIX = "speed:prefill_tps"

_OUTPUT_TG_RE = re.compile(r"^speed:output_tps(\d+)")
_PREFILL_PP_RE = re.compile(r"^speed:prefill_tps(\d+)")


def metric_mean(value: Any) -> float | None:
    """Unpack llama-benchy `{mean, std, values}` or a bare number."""
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


def implied_prompt_tokens(
    pp_throughput_mean: float | None,
    est_ppt_mean: float | None,
) -> float | None:
    """pp_throughput (tok/s) × est_ppt. llama-benchy stores est_ppt in ms when ≥ 1."""
    if pp_throughput_mean is None or est_ppt_mean is None or est_ppt_mean <= 0:
        return None
    ppt_s = est_ppt_mean / 1000.0 if est_ppt_mean >= 1.0 else est_ppt_mean
    return pp_throughput_mean * ppt_s


def decode_invalid_reason(
    token_count_mean: float | None,
    tg: int | float | None,
) -> str | None:
    if token_count_mean is None:
        return None
    if token_count_mean < MIN_DECODE_TOKENS:
        return (
            f"short EOS: output_token_count.mean={token_count_mean:.1f} "
            f"< {MIN_DECODE_TOKENS}"
        )
    if tg is not None and token_count_mean < MIN_DECODE_FRACTION_OF_TG * float(tg):
        return (
            f"short EOS: output_token_count.mean={token_count_mean:.1f} "
            f"< {MIN_DECODE_FRACTION_OF_TG} * tg={tg}"
        )
    return None


def prefill_invalid_reason(
    pp_throughput_mean: float | None,
    est_ppt_mean: float | None,
    prompt_size: int | float | None,
) -> str | None:
    if prompt_size is not None and prompt_size <= MIN_PROMPT_SIZE:
        return f"collapsed prefill: prompt_size={prompt_size} <= {MIN_PROMPT_SIZE}"
    implied = implied_prompt_tokens(pp_throughput_mean, est_ppt_mean)
    if implied is not None and implied < MIN_IMPLIED_PROMPT_TOKENS:
        return (
            f"collapsed prefill: implied_prompt_tokens={implied:.2f} "
            f"< {MIN_IMPLIED_PROMPT_TOKENS} (pp≈1 signature)"
        )
    return None


def _as_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def evaluate_speed_result(
    task_name: str,
    metrics_json: Any = None,
    raw_output_json: Any = None,
) -> str | None:
    """Return invalid_reason if this Speed cell must not keep a numeric tok/s."""
    if not task_name:
        return None
    metrics = _as_dict(metrics_json)
    raw = _as_dict(raw_output_json)
    thinking = raw.get("benchbase_thinking")
    if not isinstance(thinking, dict):
        thinking = {}

    if task_name.startswith(OUTPUT_TPS_PREFIX):
        tok = (
            metrics.get("output_token_count")
            or thinking.get("output_token_count")
            or raw.get("output_token_count")
        )
        tg = raw.get("response_size")
        if tg is None:
            match = _OUTPUT_TG_RE.match(task_name)
            if match:
                tg = int(match.group(1))
        return decode_invalid_reason(metric_mean(tok), tg)

    if task_name.startswith(PREFILL_TPS_PREFIX):
        pp = metrics.get("throughput_mean")
        if pp is None:
            pp = metric_mean(raw.get("pp_throughput"))
        elif not isinstance(pp, (int, float)):
            pp = metric_mean(pp)
        est_mean = metric_mean(metrics.get("est_ppt"))
        if est_mean is None:
            est_mean = metric_mean(raw.get("est_ppt"))
        prompt_size = raw.get("prompt_size")
        if prompt_size is None:
            match = _PREFILL_PP_RE.match(task_name)
            if match:
                prompt_size = int(match.group(1))
        return prefill_invalid_reason(
            float(pp) if isinstance(pp, (int, float)) else None,
            est_mean,
            prompt_size,
        )
    return None


def annotate_invalid_metrics(
    metrics_json: Any,
    original_score: float | None,
    reason: str,
) -> str:
    metrics = _as_dict(metrics_json)
    if "original_score" not in metrics and original_score is not None:
        metrics["original_score"] = original_score
    metrics["invalid_reason"] = reason
    return json.dumps(metrics)


def rewrite_speed_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """If the row fails the gate, return score=None plus updated metrics. Else None.

    Operates on Result-like dicts (`task_name`, `score`, `metrics_json`, `raw_output_json`).
    Does not invent a replacement tok/s.
    """
    task_name = row.get("task_name") or ""
    if not (
        task_name.startswith(OUTPUT_TPS_PREFIX) or task_name.startswith(PREFILL_TPS_PREFIX)
    ):
        return None
    metrics = _as_dict(row.get("metrics_json"))
    if row.get("score") is None and metrics.get("invalid_reason"):
        return None
    reason = evaluate_speed_result(
        task_name, row.get("metrics_json"), row.get("raw_output_json")
    )
    if reason is None:
        return None
    original = row.get("score")
    if original is None:
        original = metrics.get("original_score")
    return {
        "score": None,
        "metrics_json": annotate_invalid_metrics(row.get("metrics_json"), original, reason),
        "invalid_reason": reason,
        "original_score": original,
    }
