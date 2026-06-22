"""Execute a single benchmark run (shared by API and batch scheduler)."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging

from sqlalchemy.orm import selectinload

from benchbase.db.models import Run, RunStatus
from benchbase.db.session import get_session_factory
from benchbase.run_controller import clear_cancelled, is_cancelled, register_task, unregister_task
from benchbase.benchmark_duration import estimate_run_duration
from benchbase.benchmark_sampling import eval_mode_label
from benchbase.run_log import RunLogManager, run_log_context
from benchbase.run_timing import RunTimingTracker
from benchbase.runners.run_metadata import parse_run_metadata

logger = logging.getLogger(__name__)


async def execute_run(run_id: int, runner_cls) -> None:
    """Run a benchmark to completion and update run status in the database."""
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
            else:
                await runner.run(run, db)
                if is_cancelled(run_id):
                    run.status = RunStatus.CANCELLED
                    RunLogManager.log(run_id, "Benchmark cancelled.")
                    logger.info("Benchmark run #%d cancelled", run_id)
                else:
                    run.status = RunStatus.COMPLETED
                    logger.info("Benchmark run #%d completed", run_id)
                    RunLogManager.log(run_id, "Benchmark completed successfully.")
        except asyncio.CancelledError:
            if is_cancelled(run_id):
                run.status = RunStatus.CANCELLED
                RunLogManager.log(run_id, "Benchmark cancelled.")
                logger.info("Benchmark run #%d cancelled (user)", run_id)
            else:
                run.status = RunStatus.FAILED
                msg = (
                    "Benchmark interrupted (server reloaded or stopped). "
                    "Run the benchmark again."
                )
                run.metadata_json = json.dumps({"error": msg})
                RunLogManager.log(run_id, msg)
                logger.warning("Benchmark run #%d interrupted by shutdown", run_id)
        except Exception as exc:
            if is_cancelled(run_id):
                run.status = RunStatus.CANCELLED
                RunLogManager.log(run_id, "Benchmark cancelled.")
                logger.info("Benchmark run #%d cancelled during error", run_id)
            else:
                run.status = RunStatus.FAILED
                run.metadata_json = json.dumps({"error": str(exc)})
                logger.error("Benchmark run #%d failed: %s", run_id, exc)
                RunLogManager.log(run_id, f"Benchmark failed: {exc}")
        finally:
            run.completed_at = datetime.datetime.now(datetime.UTC)
            await db.commit()
            run_log_context.reset(token)
            clear_cancelled(run_id)
            unregister_task(run_id)
            RunLogManager.close(run_id)
