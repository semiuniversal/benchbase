"""Historical per-item duration for model × suite × tier (live ETA priors)."""

from __future__ import annotations

import statistics
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Result, ResultItem, Run, RunStatus, RunTier


async def prior_sec_per_item(
    db: AsyncSession,
    *,
    model_id: int,
    suite_id: int,
    tier: RunTier | str,
    limit: int = 8,
) -> float | None:
    """Median wall-clock seconds per scored item from recent completed runs."""
    tier_val = tier.value if isinstance(tier, RunTier) else str(tier)
    rows = (
        await db.execute(
            select(Run)
            .options(selectinload(Run.results))
            .where(
                Run.model_id == model_id,
                Run.suite_id == suite_id,
                Run.tier == tier_val,
                Run.status == RunStatus.COMPLETED,
            )
            .order_by(Run.completed_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    per_item: list[float] = []
    for run in rows:
        for res in run.results or []:
            n = res.n_items or 0
            if n < 1:
                continue
            if run.started_at and run.completed_at:
                wall = (run.completed_at - run.started_at).total_seconds()
                if wall > 0:
                    per_item.append(wall / n)
                    break
            # Fallback: mean latency_ms on items for this result.
            mean_ms = await db.scalar(
                select(func.avg(ResultItem.latency_ms)).where(
                    ResultItem.result_id == res.id,
                    ResultItem.latency_ms.isnot(None),
                )
            )
            if mean_ms and float(mean_ms) > 0:
                per_item.append(float(mean_ms) / 1000.0)

    if not per_item:
        return None
    return float(statistics.median(per_item))


def duration_estimate_from_prior(
    *,
    work_units: int,
    sec_per_item: float,
    spread: tuple[float, float] = (0.9, 1.15),
) -> dict[str, Any]:
    """Build estimate dict from observed per-item speed."""
    from benchbase.benchmark_duration import format_duration_range

    low = work_units * sec_per_item * spread[0]
    high = work_units * sec_per_item * spread[1]
    return {
        "work_units_total": work_units,
        "estimate_seconds_low": low,
        "estimate_seconds_high": high,
        "estimate_label": format_duration_range(low, high),
        "sec_per_item": sec_per_item,
        "estimate_source": "historical",
    }