"""Invalidate historical collapsed Speed/Prefill scores. Does not invent tok/s."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Result, Run
from benchbase.speed_gate import (
    OUTPUT_TPS_PREFIX,
    PREFILL_TPS_PREFIX,
    rewrite_speed_row,
)


async def collect_speed_rescore_actions(db: AsyncSession) -> list[dict[str, Any]]:
    """Scan stored output_tps / prefill_tps rows and list gate failures."""
    stmt = (
        select(Result)
        .options(selectinload(Result.run).selectinload(Run.model))
        .where(
            or_(
                Result.task_name.startswith(OUTPUT_TPS_PREFIX),
                Result.task_name.startswith(PREFILL_TPS_PREFIX),
            )
        )
        .order_by(Result.run_id, Result.id)
    )
    rows = (await db.execute(stmt)).scalars().all()
    actions: list[dict[str, Any]] = []
    for result in rows:
        patch = rewrite_speed_row(
            {
                "task_name": result.task_name,
                "score": result.score,
                "metrics_json": result.metrics_json,
                "raw_output_json": result.raw_output_json,
            }
        )
        if patch is None:
            continue
        run = result.run
        model_name = run.model.name if run and run.model else None
        actions.append(
            {
                "result_id": result.id,
                "run_id": result.run_id,
                "model": model_name,
                "task_name": result.task_name,
                "old_score": patch.get("original_score"),
                "reason": patch["invalid_reason"],
                "metrics_json": patch["metrics_json"],
            }
        )
    return actions


async def apply_speed_rescore(db: AsyncSession, actions: list[dict[str, Any]]) -> int:
    """Null scores and stash original_score + invalid_reason. Returns rows written."""
    if not actions:
        return 0
    by_id = {a["result_id"]: a for a in actions}
    stmt = select(Result).where(Result.id.in_(by_id.keys()))
    results = (await db.execute(stmt)).scalars().all()
    written = 0
    for result in results:
        action = by_id.get(result.id)
        if action is None:
            continue
        result.score = None
        result.metrics_json = action["metrics_json"]
        written += 1
    if written:
        await db.commit()
    return written


def models_needing_speed_rerun(actions: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for action in actions:
        name = action.get("model")
        if name and name not in seen:
            seen.append(name)
    return seen


async def rescore_speed_history(db: AsyncSession, apply: bool) -> dict[str, Any]:
    actions = await collect_speed_rescore_actions(db)
    written = 0
    if apply:
        written = await apply_speed_rescore(db, actions)
    return {
        "apply": apply,
        "invalidated": len(actions),
        "written": written,
        "actions": actions,
        "models_needing_rerun": models_needing_speed_rerun(actions),
    }
