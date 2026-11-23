"""Derive actionable dashboard headlines from persisted runs (D1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.batch_scheduler import batch_status_dict
from benchbase.db.models import Model, ModelStatus, Run, RunStatus

MAX_HEADLINES = 8
COMPLETED_LOOKBACK_DAYS = 7

_PRIORITY = {
    "benchmark.running": 400,
    "benchmark.queued": 350,
    "benchmark.interrupted": 300,
    "benchmark.completed": 200,
}

_TYPE_LABEL = {
    "benchmark.running": "RUNNING",
    "benchmark.queued": "QUEUED",
    "benchmark.interrupted": "INTERRUPTED",
    "benchmark.completed": "RESULT",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_meta(run: Run) -> dict[str, Any]:
    if not run.metadata_json:
        return {}
    try:
        data = json.loads(run.metadata_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def is_finalist_run(run: Run) -> bool:
    meta = _parse_meta(run)
    if meta.get("display_label"):
        return True
    suite = run.suite
    if suite and suite.runner_class == "agentic":
        return True
    return False


def rollup_status(members: list[Run]) -> str:
    statuses = {m.status.value for m in members}
    if "pausing" in statuses:
        return "pausing"
    if RunStatus.RUNNING.value in statuses:
        return RunStatus.RUNNING.value
    if RunStatus.PAUSED.value in statuses:
        return RunStatus.PAUSED.value
    if RunStatus.PENDING.value in statuses:
        return RunStatus.PENDING.value
    if RunStatus.FAILED.value in statuses:
        return RunStatus.FAILED.value
    if RunStatus.CANCELLED.value in statuses:
        return RunStatus.CANCELLED.value
    if all(m.status == RunStatus.COMPLETED for m in members):
        return RunStatus.COMPLETED.value
    return members[-1].status.value if members else "unknown"


def tier_label(tier: str | None) -> str:
    if tier == "smoke":
        return "Smoke"
    if tier == "thorough":
        return "Thorough"
    if tier == "standard":
        return "Standard"
    return tier or "Benchmark"


def _group_key(run: Run) -> str:
    return run.run_group_id or f"solo-{run.id}"


def _headline_type(rollup: str) -> str | None:
    if rollup in (RunStatus.RUNNING.value, "pausing"):
        return "benchmark.running"
    if rollup == RunStatus.PENDING.value:
        return "benchmark.queued"
    if rollup in (
        RunStatus.FAILED.value,
        RunStatus.PAUSED.value,
        RunStatus.CANCELLED.value,
    ):
        return "benchmark.interrupted"
    if rollup == RunStatus.COMPLETED.value:
        return "benchmark.completed"
    return None


def _format_age(dt: datetime | None, *, now: datetime | None = None) -> str | None:
    if dt is None:
        return None
    ref = now or _utcnow()
    if dt.tzinfo:
        dt = dt.replace(tzinfo=None)
    delta = ref - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{secs} sec ago"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        return f"{secs // 3600} hr ago"
    return f"{secs // 86400} day(s) ago"


@dataclass
class RunGroupView:
    key: str
    run_group_id: str | None
    model_id: int
    model_name: str
    tier: str
    status: str
    members: list[Run]
    updated_at: datetime | None
    completed_at: datetime | None


def build_run_groups(runs: list[Run]) -> list[RunGroupView]:
    by_key: dict[str, list[Run]] = {}
    for run in runs:
        by_key.setdefault(_group_key(run), []).append(run)

    groups: list[RunGroupView] = []
    for key, members in by_key.items():
        members = sorted(members, key=lambda r: r.id)
        if any(is_finalist_run(m) for m in members):
            continue
        model = members[0].model
        if model is None:
            continue
        tier = members[0].tier.value if members[0].tier else "standard"
        status = rollup_status(members)
        current = (
            next(
                (m for m in members if m.status == RunStatus.RUNNING),
                None,
            )
            or next((m for m in members if m.status == RunStatus.PAUSED), None)
            or next((m for m in members if m.status == RunStatus.PENDING), None)
            or members[-1]
        )
        times = [t for m in members for t in (m.started_at, m.completed_at) if t]
        updated_at = max(times) if times else None
        completed_at = None
        if all(m.status == RunStatus.COMPLETED for m in members):
            done = [m.completed_at for m in members if m.completed_at]
            completed_at = max(done) if done else None
        groups.append(
            RunGroupView(
                key=key,
                run_group_id=members[0].run_group_id,
                model_id=model.id,
                model_name=model.name,
                tier=tier,
                status=status,
                members=members,
                updated_at=updated_at or current.started_at,
                completed_at=completed_at,
            )
        )
    return groups


def _destination(group: RunGroupView) -> dict[str, Any]:
    query: dict[str, str] = {"open": "1"}
    if group.run_group_id:
        query["group"] = group.run_group_id
    else:
        solo = group.members[-1].id
        query["run_id"] = str(solo)
    return {"routeName": "benchmarks", "query": query}


def _progress_subtitle(group: RunGroupView, batch: dict[str, Any] | None) -> str:
    parts: list[str] = []
    current = next(
        (m for m in group.members if m.status == RunStatus.RUNNING),
        None,
    )
    if current and current.suite:
        parts.append(current.suite.name)
    elif batch and batch.get("current_label"):
        parts.append(str(batch["current_label"]))
    if group.run_group_id and batch and batch.get("run_group_id") == group.run_group_id:
        done = batch.get("axes_done")
        total = batch.get("axes_total")
        if isinstance(done, int) and isinstance(total, int) and total > 0:
            parts.append(f"{done}/{total} axes")
    else:
        done = sum(1 for m in group.members if m.status == RunStatus.COMPLETED)
        parts.append(f"{done}/{len(group.members)} axes")
    if group.updated_at:
        age = _format_age(group.updated_at)
        if age:
            parts.append(f"updated {age}")
    return " · ".join(parts) if parts else tier_label(group.tier)


def _interrupted_subtitle(group: RunGroupView) -> str:
    failed = next((m for m in group.members if m.status == RunStatus.FAILED), None)
    if failed:
        meta = _parse_meta(failed)
        reason = meta.get("pause_reason") or meta.get("error")
        if reason:
            return f"{tier_label(group.tier)} · {reason[:120]}"
    if group.status == RunStatus.PAUSED.value:
        return f"{tier_label(group.tier)} · paused — open for resume or diagnostics"
    if group.status == RunStatus.CANCELLED.value:
        return f"{tier_label(group.tier)} · cancelled"
    return tier_label(group.tier)


def _completed_subtitle(group: RunGroupView, *, now: datetime) -> str:
    axes = len(group.members)
    age = _format_age(group.completed_at, now=now)
    bits = [tier_label(group.tier), f"{axes} axes"]
    if age:
        bits.append(age)
    return " · ".join(bits)


def headline_from_group(
    group: RunGroupView,
    *,
    batch: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    htype = _headline_type(group.status)
    if htype is None:
        return None
    ref = now or _utcnow()
    if htype == "benchmark.completed" and group.completed_at:
        if group.completed_at < ref - timedelta(days=COMPLETED_LOOKBACK_DAYS):
            return None

    tier = tier_label(group.tier)
    title = f"{group.model_name} — {tier} benchmark"
    if htype == "benchmark.running":
        subtitle = _progress_subtitle(group, batch)
    elif htype == "benchmark.queued":
        subtitle = f"{tier} · waiting to start"
    elif htype == "benchmark.interrupted":
        subtitle = _interrupted_subtitle(group)
    else:
        subtitle = _completed_subtitle(group, now=ref)

    source_id = group.run_group_id or str(group.members[-1].id)
    occurred = group.completed_at or group.updated_at or ref
    return {
        "id": f"group:{source_id}",
        "type": htype,
        "type_label": _TYPE_LABEL[htype],
        "title": title,
        "subtitle": subtitle,
        "sourceKind": "benchmark",
        "sourceId": source_id,
        "occurredAt": occurred.isoformat() + "Z" if occurred else ref.isoformat() + "Z",
        "updatedAt": (group.updated_at or occurred).isoformat() + "Z"
        if (group.updated_at or occurred)
        else None,
        "priority": _PRIORITY[htype],
        "destination": _destination(group),
    }


def select_headlines(
    groups: list[RunGroupView],
    *,
    batch: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    ref = now or _utcnow()
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for group in groups:
        if group.key in seen:
            continue
        h = headline_from_group(group, batch=batch, now=ref)
        if h is None:
            continue
        seen.add(group.key)
        items.append(h)

    items.sort(
        key=lambda h: (
            -h["priority"],
            -(datetime.fromisoformat(h["updatedAt"].replace("Z", "")).timestamp()
              if h.get("updatedAt")
              else 0),
        ),
    )
    return items[:MAX_HEADLINES]


async def fetch_dashboard_headlines(db: AsyncSession) -> dict[str, Any]:
    archived_ids = (
        await db.execute(select(Model.id).where(Model.status == ModelStatus.ARCHIVED))
    ).scalars().all()
    archived = set(archived_ids)

    runs = (
        await db.execute(
            select(Run)
            .options(selectinload(Run.model), selectinload(Run.suite))
            .order_by(Run.id.desc())
            .limit(2000)
        )
    ).scalars().all()
    runs = [r for r in runs if r.model_id not in archived]

    groups = build_run_groups(runs)
    batch = await batch_status_dict()
    headlines = select_headlines(groups, batch=batch)
    return {
        "headlines": headlines,
        "generated_at": _utcnow().isoformat() + "Z",
        "count": len(headlines),
    }