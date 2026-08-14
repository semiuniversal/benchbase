"""Tier run-group helpers: delete and abort (cancel + wipe) atomic sets."""

from __future__ import annotations

import logging
import shutil

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.agentic.session_store import AGENTIC_DIR
from benchbase.db.models import Model, Result, ResultItem, Run, RunStatus
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
        agentic = AGENTIC_DIR / str(run_id)
        if agentic.is_dir():
            shutil.rmtree(agentic, ignore_errors=True)
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


async def delete_model_and_runs(db: AsyncSession, model_id: int) -> dict:
    """Abort in-flight work, delete every run for the model, then the model row."""
    model = await db.get(Model, model_id)
    if model is None:
        return {"deleted": False, "runs_deleted": 0}

    runs = list(
        (await db.execute(select(Run).where(Run.model_id == model_id))).scalars().all()
    )
    run_ids = [r.id for r in runs]

    groups = {
        r.run_group_id
        for r in runs
        if r.status == RunStatus.RUNNING and r.run_group_id
    }
    for gid in groups:
        await abort_run_group(db, gid)

    ungrouped = [
        r.id for r in runs if r.status == RunStatus.RUNNING and not r.run_group_id
    ]
    if ungrouped:
        from benchbase.batch_scheduler import wait_runs_not_running

        for rid in ungrouped:
            await cancel_run_controller(rid)
        await wait_runs_not_running(ungrouped, timeout=120.0)

    remaining = list(await db.scalars(select(Run.id).where(Run.model_id == model_id)))
    if remaining:
        await delete_run_ids(db, remaining)

    model = await db.get(Model, model_id)
    if model is not None:
        await db.delete(model)
        await db.commit()

    logger.info("Deleted model %s and %d run(s)", model_id, len(run_ids))
    return {"deleted": True, "runs_deleted": len(run_ids)}
