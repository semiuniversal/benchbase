"""T_eff and three-factor decomposition for the agentic suite."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from benchbase.agentic.ledger import AttemptLedger


@dataclass
class TaskMetrics:
    task_id: str
    n_attempts: int
    successes: int
    p_success: float
    mean_wall_seconds: float
    t_eff: float | None  # None / math.inf when P=0
    t_eff_infinite: bool
    mean_tokens: float
    seconds_per_token: float | None
    tokens_per_attempt: float
    reliability_inv: float | None  # 1/P
    reject_rate: float
    thrash_rate: float
    false_confidence: float | None = None  # probes only
    recovery_rate: float | None = None  # failure-injection only
    excluded_from_geomean: bool = False


def compute_task_metrics(
    task_id: str,
    ledgers: Sequence[AttemptLedger],
    *,
    expected: str = "solvable",
    failure_injection: bool = False,
) -> TaskMetrics:
    n = len(ledgers)
    if n == 0:
        return TaskMetrics(
            task_id=task_id,
            n_attempts=0,
            successes=0,
            p_success=0.0,
            mean_wall_seconds=0.0,
            t_eff=None,
            t_eff_infinite=True,
            mean_tokens=0.0,
            seconds_per_token=None,
            tokens_per_attempt=0.0,
            reliability_inv=None,
            reject_rate=0.0,
            thrash_rate=0.0,
            excluded_from_geomean=True,
        )

    successes = sum(1 for L in ledgers if L.resolved)
    p = successes / n
    mean_wall = sum(L.wall_seconds for L in ledgers) / n
    mean_tokens = sum(L.tokens_total for L in ledgers) / n
    spt = (mean_wall / mean_tokens) if mean_tokens > 0 else None
    rejects = sum(L.hashline_rejected_edits for L in ledgers)
    tools = sum(max(L.tool_calls, 1) for L in ledgers)
    thrash = sum(1 for L in ledgers if L.thrash_cutoffs or L.cutoff_reason == "thrash")

    t_eff: float | None
    infinite = False
    excluded = False
    if expected == "unsolvable":
        # Calibration probes are not in T_eff geo-mean.
        t_eff = None
        infinite = False
        excluded = True
        false_conf = sum(1 for L in ledgers if L.resolved is True or (not L.abstained and L.resolved is not False)) / n
        # Prefer explicit: false confidence = fabrication without abstention.
        false_conf = sum(1 for L in ledgers if not L.abstained) / n
        return TaskMetrics(
            task_id=task_id,
            n_attempts=n,
            successes=successes,
            p_success=p,
            mean_wall_seconds=mean_wall,
            t_eff=None,
            t_eff_infinite=False,
            mean_tokens=mean_tokens,
            seconds_per_token=spt,
            tokens_per_attempt=mean_tokens,
            reliability_inv=None,
            reject_rate=rejects / tools,
            thrash_rate=thrash / n,
            false_confidence=false_conf,
            excluded_from_geomean=True,
        )

    if p <= 0:
        t_eff = math.inf
        infinite = True
        excluded = True
        rel_inv = None
    else:
        t_eff = mean_wall / p
        rel_inv = 1.0 / p

    recovery = None
    if failure_injection and n:
        recovery = successes / n

    return TaskMetrics(
        task_id=task_id,
        n_attempts=n,
        successes=successes,
        p_success=p,
        mean_wall_seconds=mean_wall,
        t_eff=t_eff,
        t_eff_infinite=infinite,
        mean_tokens=mean_tokens,
        seconds_per_token=spt,
        tokens_per_attempt=mean_tokens,
        reliability_inv=rel_inv,
        reject_rate=rejects / tools,
        thrash_rate=thrash / n,
        recovery_rate=recovery,
        excluded_from_geomean=excluded,
    )


def geometric_mean_teff_ratio(
    candidate: Sequence[TaskMetrics],
    reference: Sequence[TaskMetrics],
) -> dict[str, Any]:
    """SPEC-style geo-mean of per-task T_eff(ref)/T_eff(cand). Self-ratio → 1.0."""
    ref_map = {t.task_id: t for t in reference}
    ratios: list[float] = []
    skipped: list[str] = []
    for c in candidate:
        if c.excluded_from_geomean or c.t_eff is None or c.t_eff_infinite:
            skipped.append(c.task_id)
            continue
        r = ref_map.get(c.task_id)
        if not r or r.excluded_from_geomean or r.t_eff is None or r.t_eff_infinite:
            skipped.append(c.task_id)
            continue
        if c.t_eff <= 0:
            skipped.append(c.task_id)
            continue
        ratios.append(r.t_eff / c.t_eff)
    if not ratios:
        return {
            "geo_mean": None,
            "n_tasks": 0,
            "skipped": skipped,
            "note": "no finite T_eff pairs",
        }
    log_sum = sum(math.log(x) for x in ratios)
    geo = math.exp(log_sum / len(ratios))
    return {
        "geo_mean": geo,
        "n_tasks": len(ratios),
        "skipped": skipped,
        "ratios": ratios,
    }


def task_metrics_to_dict(m: TaskMetrics) -> dict[str, Any]:
    d = {
        "task_id": m.task_id,
        "n_attempts": m.n_attempts,
        "successes": m.successes,
        "p_success": m.p_success,
        "mean_wall_seconds": m.mean_wall_seconds,
        "t_eff": None if m.t_eff is None or (isinstance(m.t_eff, float) and math.isinf(m.t_eff)) else m.t_eff,
        "t_eff_infinite": m.t_eff_infinite,
        "mean_tokens": m.mean_tokens,
        "seconds_per_token": m.seconds_per_token,
        "tokens_per_attempt": m.tokens_per_attempt,
        "reliability_inv": m.reliability_inv,
        "reject_rate": m.reject_rate,
        "thrash_rate": m.thrash_rate,
        "false_confidence": m.false_confidence,
        "recovery_rate": m.recovery_rate,
        "excluded_from_geomean": m.excluded_from_geomean,
    }
    return d
