"""Tier run-group helpers: delete and abort (cancel + wipe) atomic sets."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Result, ResultItem, Run, RunStatus
from benchbase.run_controller import cancel_run as cancel_run_controller, reset_run_tracking
from benchbase.run_log import RunLogManager

logger = logging.getLogger(__name__)


async def list_group_runs(db: AsyncSession, run_group_id: str) -> list[Run]:
    result = await db.execute(
        select(Run).where(Run.run_group_id == run_group_id).order_by(Run.id)
    )
    return list(result.scalars().all())


async def delete_run_ids(db: AsyncSession, run_ids: list[int]) -> int:
    """Delete runs and their results/items/logs. Commits the session."""
    if not run_ids:
        return 0
    result_ids = list(
        await db.scalars(select(Result.id).where(Result.run_id.in_(run_ids)))
    )
    if result_ids:
        await db.execute(delete(ResultItem).where(ResultItem.result_id.in_(result_ids)))
        await db.execute(delete(Result).where(Result.id.in_(result_ids)))
    await db.execute(delete(Run).where(Run.id.in_(run_ids)))
    await db.commit()
    for run_id in run_ids:
        RunLogManager.remove(run_id)
        reset_run_tracking(run_id)
    return len(run_ids)


async def delete_run_group(db: AsyncSession, run_group_id: str) -> int:
    """Delete every run in a group. Caller must ensure nothing is running, or use abort."""
    runs = await list_group_runs(db, run_group_id)
    if not runs:
        return 0
    if any(r.status == RunStatus.RUNNING for r in runs):
        raise RuntimeError("Cannot delete a run group while a member is still running; abort instead.")
    return await delete_run_ids(db, [r.id for r in runs])


def _batch_id_from_group(run_group_id: str) -> str | None:
    # run_group_id is "tier-{batch_id}"
    if run_group_id.startswith("tier-"):
        return run_group_id[len("tier-") :]
    return None


async def abort_run_group(db: AsyncSession, run_group_id: str) -> dict:
    """Cancel in-flight work for the group, skip remaining axes, then wipe all members."""
    from benchbase.batch_scheduler import mark_batch_cancelled, wait_runs_not_running

    runs = await list_group_runs(db, run_group_id)
    if not runs:
        return {"aborted": True, "deleted": 0, "run_group_id": run_group_id}

    batch_id = _batch_id_from_group(run_group_id)
    if batch_id:
        mark_batch_cancelled(batch_id)

    running_ids = [r.id for r in runs if r.status == RunStatus.RUNNING]
    for rid in running_ids:
        await cancel_run_controller(rid)
        RunLogManager.log(rid, "Abort requested — discarding entire tier set…")

    # Mark pending siblings cancelled so the worker skips them quickly.
    for run in runs:
        if run.status == RunStatus.PENDING:
            run.status = RunStatus.CANCELLED
    await db.commit()

    if running_ids:
        await wait_runs_not_running(running_ids, timeout=120.0)

    # Re-fetch and delete everything in the group.
    await db.rollback()
    runs = await list_group_runs(db, run_group_id)
    deleted = await delete_run_ids(db, [r.id for r in runs])
    logger.info("Aborted run group %s — deleted %d runs", run_group_id, deleted)
    return {"aborted": True, "deleted": deleted, "run_group_id": run_group_id}
