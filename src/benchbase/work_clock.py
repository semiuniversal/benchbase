"""Derived work clock: seconds of scored quality work per correct item.

Computed from existing Standard (else Smoke) sittings. Not a new suite.
Speed / Smoke coherency / Agentic are excluded. A failed Speed sibling does
not disqualify the sitting.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Run, RunStatus
from benchbase.runners.run_metadata import parse_run_metadata

logger = logging.getLogger(__name__)

WORK_CLOCK_AXES: tuple[str, ...] = (
    "knowledge",
    "reasoning",
    "math",
    "coding",
    "tool_calling",
    "instruction",
    "structured",
    "long_context",
)

CONTAMINATED_GROUP_IDS = frozenset({"tier-99b1925bd139"})
CONTAMINATED_REASON = (
    "sticky LiteLLM min_tokens: 2048 turned quality into 2048-token dumps"
)

EMPTY_CLOCK: dict[str, Any] = {
    "sec_per_correct": None,
    "suite_wall_s": None,
    "n_correct": None,
    "work_clock_tier": None,
    "invalid_reason": None,
    "work_clock_group": None,
    "work_clock_index": None,
    "work_clock_reference": None,
    "work_clock_reference_sec": None,
}

_STANDARDISH = frozenset({"standard", "thorough"})
N_CORRECT_DRIFT_MAX = 50


@dataclass
class AxisWall:
    axis: str
    run_id: int
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    successes: int
    active_ms: float | None = None


@dataclass
class Sitting:
    run_group_id: str
    model_id: int
    model_name: str
    tier: str
    axes: dict[str, AxisWall] = field(default_factory=dict)


def successes_from_metrics(metrics_json: str | None) -> int:
    if not metrics_json:
        return 0
    try:
        payload = json.loads(metrics_json)
    except json.JSONDecodeError:
        return 0
    raw = payload.get("successes") if isinstance(payload, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0
    return int(raw)


def quality_complete(sitting: Sitting) -> bool:
    return all(
        (wall := sitting.axes.get(axis)) is not None
        and wall.status == RunStatus.COMPLETED.value
        for axis in WORK_CLOCK_AXES
    )


def suite_wall_s(sitting: Sitting) -> float | None:
    total = 0.0
    for axis in WORK_CLOCK_AXES:
        wall = sitting.axes.get(axis)
        if wall is None:
            return None
        if wall.active_ms is not None and wall.active_ms >= 0:
            total += wall.active_ms / 1000.0
            continue
        if wall.started_at is None or wall.completed_at is None:
            return None
        delta = (wall.completed_at - wall.started_at).total_seconds()
        if delta < 0:
            return None
        total += delta
    return total


def n_correct(sitting: Sitting) -> int:
    return sum(
        sitting.axes[axis].successes
        for axis in WORK_CLOCK_AXES
        if axis in sitting.axes
    )


def sitting_recency(sitting: Sitting) -> int:
    return max((w.run_id for w in sitting.axes.values()), default=0)


def pick_sitting(sittings: list[Sitting]) -> Sitting | None:
    """Latest Standard/Thorough quality sitting, else latest complete Smoke."""
    complete = [s for s in sittings if quality_complete(s)]
    standardish = [s for s in complete if s.tier in _STANDARDISH]
    pool = standardish or [s for s in complete if s.tier == "smoke"]
    if not pool:
        return None
    return max(pool, key=sitting_recency)


def work_clock_payload(sitting: Sitting | None) -> dict[str, Any]:
    if sitting is None:
        return dict(EMPTY_CLOCK)
    wall = suite_wall_s(sitting)
    correct = n_correct(sitting)
    contaminated = sitting.run_group_id in CONTAMINATED_GROUP_IDS
    sec: float | None = None
    if not contaminated and wall is not None and correct > 0:
        sec = round(wall / correct, 2)
    return {
        "sec_per_correct": sec,
        "suite_wall_s": None if wall is None else round(wall, 1),
        "n_correct": correct,
        "work_clock_tier": sitting.tier,
        "invalid_reason": CONTAMINATED_REASON if contaminated else None,
        "work_clock_group": sitting.run_group_id,
    }


def _index_tier(tier: str | None) -> str | None:
    if not tier:
        return None
    if tier in _STANDARDISH:
        return "standard"
    if tier == "smoke":
        return "smoke"
    return tier


def compute_speed_index(
    reference: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> int | None:
    """Relative work-clock index: reference = 100, higher is faster."""
    if not reference or not candidate:
        return None
    r_sec = reference.get("sec_per_correct")
    a_sec = candidate.get("sec_per_correct")
    if not isinstance(r_sec, (int, float)) or not isinstance(a_sec, (int, float)):
        return None
    if r_sec <= 0 or a_sec <= 0:
        return None
    if reference.get("invalid_reason") or candidate.get("invalid_reason"):
        return None
    if _index_tier(reference.get("work_clock_tier")) != _index_tier(
        candidate.get("work_clock_tier")
    ):
        return None
    r_n = reference.get("n_correct")
    a_n = candidate.get("n_correct")
    if isinstance(r_n, (int, float)) and isinstance(a_n, (int, float)):
        if abs(int(a_n) - int(r_n)) > N_CORRECT_DRIFT_MAX:
            return None
    return int(round((float(r_sec) / float(a_sec)) * 100))


def attach_speed_indexes(
    clocks: dict[str, dict[str, Any]],
    reference_name: str | None,
) -> dict[str, dict[str, Any]]:
    """Stamp work_clock_index fields onto per-model clock payloads (in place)."""
    ref_name = (reference_name or "").strip() or None
    ref = clocks.get(ref_name) if ref_name else None
    ref_sec = ref.get("sec_per_correct") if ref else None
    for clock in clocks.values():
        clock["work_clock_reference"] = ref_name
        clock["work_clock_reference_sec"] = ref_sec if isinstance(ref_sec, (int, float)) else None
        clock["work_clock_index"] = compute_speed_index(ref, clock) if ref_name else None
    return clocks


def _axis_of(run: Run) -> str | None:
    if not run.suite:
        return None
    axis = run.suite.axis.value if run.suite.axis else None
    return axis if axis in WORK_CLOCK_AXES else None


def _successes_for_run(run: Run) -> int:
    return sum(successes_from_metrics(r.metrics_json) for r in (run.results or []))


def _active_ms_for_run(run: Run) -> float | None:
    if not hasattr(run, "metadata_json"):
        return None
    meta = parse_run_metadata(run)
    raw = meta.get("active_ms")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    return None


def sittings_from_runs(runs: list[Run]) -> list[Sitting]:
    grouped: dict[tuple[int, str], Sitting] = {}
    for run in runs:
        if not run.run_group_id:
            continue
        model = run.model
        model_id = run.model_id
        model_name = model.name if model else ""
        key = (model_id, run.run_group_id)
        sitting = grouped.get(key)
        if sitting is None:
            sitting = Sitting(
                run_group_id=run.run_group_id,
                model_id=model_id,
                model_name=model_name,
                tier=run.tier.value if run.tier else "standard",
            )
            grouped[key] = sitting
        axis = _axis_of(run)
        if axis is None:
            continue
        status = run.status.value if run.status else RunStatus.PENDING.value
        existing = sitting.axes.get(axis)
        if existing is not None and existing.run_id > run.id:
            continue
        sitting.axes[axis] = AxisWall(
            axis=axis,
            run_id=run.id,
            status=status,
            started_at=run.started_at,
            completed_at=run.completed_at,
            successes=_successes_for_run(run),
            active_ms=_active_ms_for_run(run),
        )
        if run.tier:
            sitting.tier = run.tier.value
    return list(grouped.values())


async def load_grouped_runs(db: AsyncSession) -> list[Run]:
    stmt = (
        select(Run)
        .options(
            selectinload(Run.model),
            selectinload(Run.suite),
            selectinload(Run.results),
        )
        .where(Run.run_group_id.is_not(None))
        .order_by(Run.id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def compute_work_clocks_by_model(db: AsyncSession) -> dict[str, dict[str, Any]]:
    sittings = sittings_from_runs(await load_grouped_runs(db))
    by_model: dict[str, list[Sitting]] = {}
    for sitting in sittings:
        if sitting.model_name:
            by_model.setdefault(sitting.model_name, []).append(sitting)
    return {
        name: work_clock_payload(pick_sitting(group))
        for name, group in by_model.items()
    }


def sitting_report_row(sitting: Sitting, *, selected: bool) -> dict[str, Any]:
    payload = work_clock_payload(sitting)
    payload["selected"] = selected
    payload["model"] = sitting.model_name
    payload["run_group_id"] = sitting.run_group_id
    payload["quality_complete"] = quality_complete(sitting)
    payload["contaminated"] = sitting.run_group_id in CONTAMINATED_GROUP_IDS
    return payload


async def collect_work_clock_report(db: AsyncSession) -> list[dict[str, Any]]:
    sittings = sittings_from_runs(await load_grouped_runs(db))
    by_model: dict[str, list[Sitting]] = {}
    for sitting in sittings:
        by_model.setdefault(sitting.model_name or f"id:{sitting.model_id}", []).append(
            sitting
        )
    rows: list[dict[str, Any]] = []
    for group in by_model.values():
        chosen = pick_sitting(group)
        for sitting in sorted(group, key=sitting_recency, reverse=True):
            if not quality_complete(sitting) and sitting is not chosen:
                continue
            rows.append(sitting_report_row(sitting, selected=sitting is chosen))
    rows.sort(
        key=lambda r: (
            r.get("model") or "",
            not r.get("selected"),
            r.get("run_group_id") or "",
        )
    )
    return rows


async def stamp_contaminated_groups(db: AsyncSession) -> int:
    """Write invalid_reason onto runs in hard-coded contaminated groups."""
    stmt = select(Run).where(Run.run_group_id.in_(CONTAMINATED_GROUP_IDS))
    runs = list((await db.execute(stmt)).scalars().all())
    written = 0
    for run in runs:
        meta = parse_run_metadata(run)
        if meta.get("invalid_reason") == CONTAMINATED_REASON:
            continue
        meta["invalid_reason"] = CONTAMINATED_REASON
        meta["work_clock_skip"] = True
        run.metadata_json = json.dumps(meta)
        written += 1
    if written:
        await db.commit()
    logger.info("Stamped contaminated work-clock metadata on %d run(s)", written)
    return written


async def rescore_work_clock(db: AsyncSession, apply: bool) -> dict[str, Any]:
    rows = await collect_work_clock_report(db)
    written = 0
    if apply:
        written = await stamp_contaminated_groups(db)
    return {
        "apply": apply,
        "sittings": rows,
        "written": written,
        "contaminated_groups": sorted(CONTAMINATED_GROUP_IDS),
    }
