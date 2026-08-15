"""Execute a single benchmark run (shared by API and batch scheduler)."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import time

from sqlalchemy.orm import selectinload

from benchbase.db.models import Run, RunStatus
from benchbase.db.session import commit_with_busy_retry, force_run_status, get_session_factory
from benchbase.run_controller import (
    clear_cancelled,
    clear_pause,
    is_cancelled,
    is_pause_requested,
    register_task,
    unregister_task,
)
from benchbase.benchmark_duration import estimate_run_duration
from benchbase.benchmark_sampling import eval_mode_label
from benchbase.run_log import RunLogManager, run_log_context
from benchbase.run_timing import RunTimingTracker
from benchbase.runners.run_metadata import parse_run_metadata

logger = logging.getLogger(__name__)


def _stamp_active_wall(run: Run, slice_start: float) -> None:
    """Add wall time since slice_start into metadata active_ms."""
    elapsed_ms = (time.monotonic() - slice_start) * 1000.0
    if elapsed_ms <= 0:
        return
    meta = parse_run_metadata(run)
    meta["active_ms"] = float(meta.get("active_ms") or 0.0) + elapsed_ms
    # Keep item latencies and wall slices in the same bucket; prefer max later if needed.
    run.metadata_json = json.dumps(meta)


async def execute_run(run_id: int, runner_cls) -> None:
    """Run a benchmark to completion/pause and update run status in the database."""
    factory = get_session_factory()

    RunLogManager.open(run_id)
    token = run_log_context.set(run_id)
    RunLogManager.log(run_id, f"Benchmark run #{run_id} started")

    meta = {}
    async with factory() as db:
        run_preview = await db.get(Run, run_id)
        if run_preview and run_preview.metadata_json:
            meta = parse_run_metadata(run_preview)
    eval_mode = meta.get("eval_mode")
    if eval_mode:
        RunLogManager.log(
            run_id,
            f"Eval mode: {eval_mode} — {eval_mode_label(str(eval_mode))}.",
        )
    if meta.get("full_benchmark"):
        RunLogManager.log(
            run_id,
            "WARNING: Full benchmark — no sample caps. Reasoning can take hours or days on slow models.",
        )

    current_task = asyncio.current_task()
    if current_task is not None:
        register_task(run_id, current_task)

    clear_pause(run_id)
    slice_start = time.monotonic()

    async with factory() as db:
        run = await db.get(
            Run, run_id, options=[selectinload(Run.suite), selectinload(Run.model)]
        )
        if not run:
            RunLogManager.log(run_id, "Run record not found in database.")
            run_log_context.reset(token)
            RunLogManager.close(run_id)
            return

        run_meta = parse_run_metadata(run)
        duration_est = estimate_run_duration(run.suite.runner_class, run_meta)
        RunTimingTracker.start(run_id, run.suite.runner_class, duration_est)
        RunLogManager.log(
            run_id,
            f"Rough time estimate: {duration_est['estimate_label']} "
            f"({duration_est['work_units_total']} work units).",
        )

        outcome: str | None = None
        try:
            runner = runner_cls()
            logger.info("Starting benchmark run #%d (%s)", run_id, run.suite.runner_class)
            RunLogManager.log(
                run_id,
                f"Suite: {run.suite.name} · Model: {run.model.name} · "
                f"Runner: {run.suite.runner_class}",
            )
            if is_cancelled(run_id):
                run.status = RunStatus.CANCELLED
                RunLogManager.log(run_id, "Benchmark cancelled.")
                outcome = "cancelled"
            else:
                outcome = await runner.run(run, db)
                if outcome is None:
                    outcome = "completed"
                if is_cancelled(run_id) or outcome == "cancelled":
                    run.status = RunStatus.CANCELLED
                    RunLogManager.log(run_id, "Benchmark cancelled.")
                    logger.info("Benchmark run #%d cancelled", run_id)
                    outcome = "cancelled"
                elif outcome == "paused" or is_pause_requested(run_id):
                    _stamp_active_wall(run, slice_start)
                    run.status = RunStatus.PAUSED
                    run.completed_at = None
                    RunLogManager.log(run_id, "Benchmark paused — progress kept.")
                    logger.info("Benchmark run #%d paused", run_id)
                    outcome = "paused"
                else:
                    run.status = RunStatus.COMPLETED
                    logger.info("Benchmark run #%d completed", run_id)
                    RunLogManager.log(run_id, "Benchmark completed successfully.")
                    outcome = "completed"
        except asyncio.CancelledError:
            if is_cancelled(run_id):
                run.status = RunStatus.CANCELLED
                RunLogManager.log(run_id, "Benchmark cancelled.")
                logger.info("Benchmark run #%d cancelled (user)", run_id)
                outcome = "cancelled"
            elif is_pause_requested(run_id):
                _stamp_active_wall(run, slice_start)
                run.status = RunStatus.PAUSED
                run.completed_at = None
                RunLogManager.log(run_id, "Benchmark paused — progress kept.")
                outcome = "paused"
            else:
                # Treat unexpected cancel (reload) as pause so checkpoints survive.
                _stamp_active_wall(run, slice_start)
                run.status = RunStatus.PAUSED
                run.completed_at = None
                msg = "Interrupted by server reload — paused with progress kept."
                meta_err = parse_run_metadata(run)
                meta_err["pause_reason"] = msg
                run.metadata_json = json.dumps(meta_err)
                RunLogManager.log(run_id, msg)
                logger.warning("Benchmark run #%d interrupted → paused", run_id)
                outcome = "paused"
        except Exception as exc:
            if is_cancelled(run_id):
                run.status = RunStatus.CANCELLED
                RunLogManager.log(run_id, "Benchmark cancelled.")
                logger.info("Benchmark run #%d cancelled during error", run_id)
                outcome = "cancelled"
            else:
                # SQLite lock under parallel model concurrency — pause so resume keeps checkpoints.
                from benchbase.db.session import _is_sqlite_busy_error

                if _is_sqlite_busy_error(exc):
                    _stamp_active_wall(run, slice_start)
                    run.status = RunStatus.PAUSED
                    run.completed_at = None
                    meta_err = parse_run_metadata(run)
                    meta_err["pause_reason"] = (
                        "Paused after database contention — resume to continue."
                    )
                    meta_err["error"] = str(exc)[:500]
                    run.metadata_json = json.dumps(meta_err)
                    logger.warning(
                        "Benchmark run #%d paused after DB contention: %s", run_id, exc
                    )
                    RunLogManager.log(
                        run_id,
                        "Paused after database contention — progress kept; resume when ready.",
                    )
                    outcome = "paused"
                else:
                    run.status = RunStatus.FAILED
                    meta_err = parse_run_metadata(run)
                    meta_err["error"] = str(exc)
                    run.metadata_json = json.dumps(meta_err)
                    logger.error("Benchmark run #%d failed: %s", run_id, exc)
                    RunLogManager.log(run_id, f"Benchmark failed: {exc}")
                    outcome = "failed"
        finally:
            if outcome != "paused":
                run.completed_at = datetime.datetime.now(datetime.UTC)
                if outcome == "completed":
                    _stamp_active_wall(run, slice_start)
            try:
                await commit_with_busy_retry(db)
            except Exception as commit_exc:
                logger.exception(
                    "Run #%d status commit failed (%s); forcing via fresh session",
                    run_id,
                    commit_exc,
                )
                try:
                    await db.rollback()
                except Exception:
                    pass
                force_status = (
                    RunStatus.PAUSED
                    if outcome == "paused"
                    else RunStatus.CANCELLED
                    if outcome == "cancelled"
                    else RunStatus.FAILED
                    if outcome == "failed"
                    else RunStatus.COMPLETED
                    if outcome == "completed"
                    else RunStatus.PAUSED
                )
                await force_run_status(
                    run_id,
                    force_status,
                    pause_reason=(
                        "Interrupted — progress kept. Resume when ready."
                        if force_status == RunStatus.PAUSED
                        else None
                    ),
                    error=str(commit_exc)[:500] if force_status == RunStatus.FAILED else None,
                )
                outcome = (
                    "paused"
                    if force_status == RunStatus.PAUSED
                    else outcome or "failed"
                )
            run_log_context.reset(token)
            clear_cancelled(run_id)
            clear_pause(run_id)
            unregister_task(run_id)
            RunLogManager.close(run_id)
