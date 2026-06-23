"""Benchmark run management routes."""

from __future__ import annotations

import asyncio
import datetime
import json

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.benchmark_duration import estimate_run_duration
from benchbase.benchmark_sampling import build_run_metadata
from benchbase.batch_scheduler import batch_status_dict, cancel_batch, is_batch_running, start_batch
from benchbase.db.models import BenchmarkSuite, Model, Result, Run, RunStatus
from benchbase.db.session import get_db
from benchbase.run_controller import cancel_run as cancel_run_controller, clear_cancelled, reset_run_tracking
from benchbase.run_executor import execute_run
from benchbase.run_log import RunLogManager, run_log_context
from benchbase.run_timing import RunTimingTracker
from benchbase.runners.registry import runner_registry
from sse_starlette.sse import EventSourceResponse

router = APIRouter()


class RunCreate(BaseModel):
    model_id: int = Field(description="Database ID of the model to benchmark.")
    suite_id: int = Field(description="Database ID of the benchmark suite to run.")
    eval_mode: Literal["routine", "full"] = Field(
        default="routine",
        description="routine uses configured sample limits; full runs entire datasets.",
    )
    metadata: dict | None = Field(
        default=None,
        description="Optional run metadata override (eval_mode, limit, etc.).",
    )


class ResultSummary(BaseModel):
    task_name: str
    score: float | None


class RunOut(BaseModel):
    id: int
    model_id: int
    suite_id: int
    status: str
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    results: list[ResultSummary] = []

    model_config = {"from_attributes": True}


def _run_to_out(run: Run, results: list[Result] | None = None) -> RunOut:
    res = results if results is not None else []
    return RunOut(
        id=run.id,
        model_id=run.model_id,
        suite_id=run.suite_id,
        status=run.status.value,
        started_at=run.started_at,
        completed_at=run.completed_at,
        results=[ResultSummary(task_name=r.task_name, score=r.score) for r in res],
    )


@router.post(
    "/runs",
    operation_id="create_benchmark_run",
    summary="Create a benchmark run",
    description="Queue a new run for a model and suite. Does not start execution; call start_benchmark_run.",
    response_model=RunOut,
)
async def create_run(body: RunCreate, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, body.model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    suite = await db.get(BenchmarkSuite, body.suite_id)
    if not suite:
        raise HTTPException(404, "Benchmark suite not found")

    if body.metadata is not None:
        run_meta = body.metadata
    else:
        run_meta = build_run_metadata(body.eval_mode, suite.runner_class)

    run = Run(
        model_id=body.model_id,
        suite_id=body.suite_id,
        status=RunStatus.PENDING,
        metadata_json=json.dumps(run_meta),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    reset_run_tracking(run.id)
    return _run_to_out(run)


@router.get(
    "/runs",
    operation_id="list_benchmark_runs",
    summary="List benchmark runs",
    description="Return the 50 most recent benchmark runs with result summaries.",
    response_model=list[RunOut],
)
async def list_runs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Run).options(selectinload(Run.results)).order_by(Run.id.desc()).limit(50)
    )
    runs = result.scalars().all()
    return [_run_to_out(r, r.results) for r in runs]


@router.get(
    "/runs/{run_id}",
    operation_id="get_benchmark_run",
    summary="Get a benchmark run",
    description="Fetch one run by ID including per-task result summaries.",
    response_model=RunOut,
)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Run).options(selectinload(Run.results)).where(Run.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Run not found")
    return _run_to_out(run, run.results)


@router.get(
    "/runs/{run_id}/timing",
    operation_id="get_benchmark_run_timing",
    summary="Get benchmark run timing",
    description="Elapsed time, static estimate, and live ETA when progress is visible in logs.",
)
async def get_run_timing(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    started_wall: float | None = None
    if run.started_at:
        started_wall = run.started_at.timestamp()

    live = RunTimingTracker.status(run_id, started_wall)
    if live:
        return live

    if run.status.value in ("pending", "running"):
        suite = await db.get(BenchmarkSuite, run.suite_id)
        meta = json.loads(run.metadata_json) if run.metadata_json else {}
        if suite:
            est = estimate_run_duration(suite.runner_class, meta)
            return {
                "elapsed_seconds": 0,
                "elapsed_label": "0 sec",
                "estimate_label": est["estimate_label"],
                "eta_seconds": None,
                "eta_label": None,
                "progress_percent": None,
                "progress_label": None,
                "work_units_done": 0,
                "work_units_total": est["work_units_total"],
            }

    return {
        "elapsed_seconds": 0,
        "elapsed_label": "—",
        "estimate_label": "—",
        "eta_seconds": None,
        "eta_label": None,
        "progress_percent": None,
        "progress_label": None,
        "work_units_done": 0,
        "work_units_total": 0,
    }


@router.get(
    "/estimate",
    operation_id="estimate_benchmark",
    summary="Estimate benchmark duration",
    description="Preview rough duration before launching a run for a suite and eval mode.",
)
async def estimate_benchmark(
    suite_id: int,
    eval_mode: str = "routine",
    db: AsyncSession = Depends(get_db),
):
    """Preview rough duration before launching a run."""
    suite = await db.get(BenchmarkSuite, suite_id)
    if not suite:
        raise HTTPException(404, "Suite not found")
    if eval_mode not in ("routine", "full", "batch"):
        raise HTTPException(400, "eval_mode must be routine, full, or batch")

    meta = build_run_metadata(eval_mode, suite.runner_class)
    est = estimate_run_duration(suite.runner_class, meta)
    return {
        "runner_class": suite.runner_class,
        "eval_mode": eval_mode,
        **est,
    }


@router.delete(
    "/runs/{run_id}",
    operation_id="delete_benchmark_run",
    summary="Delete a benchmark run",
    description="Remove a run and its results. Cannot delete a run that is still in progress.",
)
async def delete_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status == RunStatus.RUNNING:
        raise HTTPException(400, "Cannot delete a run that is still in progress")

    result = await db.execute(select(Result).where(Result.run_id == run_id))
    for row in result.scalars().all():
        await db.delete(row)
    RunLogManager.remove(run_id)
    reset_run_tracking(run_id)
    await db.delete(run)
    await db.commit()
    return {"deleted": True}


@router.post(
    "/runs/{run_id}/cancel",
    operation_id="cancel_benchmark_run",
    summary="Cancel a benchmark run",
    description="Stop a running benchmark and kill its subprocess.",
)
async def cancel_run(run_id: int, db: AsyncSession = Depends(get_db)):
    """Stop a running benchmark and kill its subprocess."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != RunStatus.RUNNING:
        raise HTTPException(400, f"Run is not running (status: {run.status.value})")

    stopped = await cancel_run_controller(run_id)
    RunLogManager.log(run_id, "Cancellation requested…")

    if not stopped:
        # Orphan: DB says running but no in-memory task (e.g. server restarted mid-run).
        clear_cancelled(run_id)
        run.status = RunStatus.CANCELLED
        run.completed_at = datetime.datetime.now(datetime.UTC)
        await db.commit()
        RunLogManager.log(run_id, "Benchmark cancelled (orphaned run).")
        RunLogManager.close(run_id)
        return {"status": "cancelled", "run_id": run_id}

    return {"status": "cancelling", "run_id": run_id}


@router.post(
    "/runs/{run_id}/start",
    operation_id="start_benchmark_run",
    summary="Start a benchmark run",
    description="Begin execution of a pending run using the suite's registered runner.",
)
async def start_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id, options=[selectinload(Run.suite), selectinload(Run.model)])
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != RunStatus.PENDING:
        raise HTTPException(400, f"Run is already {run.status.value}")

    if is_batch_running():
        raise HTTPException(409, "A full benchmark batch is running")

    runner_cls = runner_registry.get(run.suite.runner_class)
    if not runner_cls:
        raise HTTPException(400, f"Unknown runner: {run.suite.runner_class}")

    run.status = RunStatus.RUNNING
    run.started_at = datetime.datetime.now(datetime.UTC)
    await db.commit()

    run_id_copy = run.id
    reset_run_tracking(run_id_copy)

    asyncio.create_task(execute_run(run_id_copy, runner_cls))

    return {"status": "running"}


@router.get(
    "/runs/{run_id}/log",
    operation_id="stream_run_log",
    summary="Stream benchmark run log (SSE)",
    description=(
        "Stream benchmark CLI output via Server-Sent Events. "
        "Not exposed as an MCP tool; use get_benchmark_run_log_history instead."
    ),
)
async def stream_run_log(run_id: int, db: AsyncSession = Depends(get_db)):
    """Stream benchmark CLI output via SSE (replay + live)."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    async def event_generator():
        buffer = RunLogManager.get(run_id)

        if buffer is None and RunLogManager.has_disk_log(run_id):
            async for entry in RunLogManager.replay_disk(run_id):
                yield {
                    "event": "log",
                    "data": json.dumps({"stream": entry.stream, "text": entry.text}),
                }
            refreshed = await db.get(Run, run_id)
            status = refreshed.status.value if refreshed else run.status.value
            yield {"event": "done", "data": json.dumps({"status": status})}
            return

        if buffer is None:
            for _ in range(30):
                await asyncio.sleep(1)
                buffer = RunLogManager.get(run_id)
                if buffer is not None:
                    break
            if buffer is None:
                yield {
                    "event": "log",
                    "data": json.dumps(
                        {"stream": "system", "text": "No log recorded for this run.\n"}
                    ),
                }
                yield {"event": "done", "data": json.dumps({"status": run.status.value})}
                return

        async for entry in buffer.subscribe():
            yield {
                "event": "log",
                "data": json.dumps({"stream": entry.stream, "text": entry.text}),
            }

        refreshed = await db.get(Run, run_id)
        status = refreshed.status.value if refreshed else "unknown"
        yield {"event": "done", "data": json.dumps({"status": status})}

    return EventSourceResponse(event_generator())


@router.get(
    "/runs/{run_id}/log/history",
    operation_id="get_benchmark_run_log_history",
    summary="Get benchmark run log history",
    description="Return the full persisted log for a run as JSON lines.",
)
async def get_run_log_history(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    lines = RunLogManager.read_disk_log(run_id)
    return {
        "lines": [{"stream": line.stream, "text": line.text} for line in lines],
    }


@router.post(
    "/batch/start",
    operation_id="start_benchmark_batch",
    summary="Start benchmark batch",
    description="Run all enabled benchmark suites once for each active model (sequential).",
)
async def batch_start():
    """Run all benchmark suites once for each active model (sequential)."""
    try:
        return await start_batch()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.get(
    "/batch/status",
    operation_id="get_benchmark_batch_status",
    summary="Get benchmark batch status",
    description="Current batch progress, or idle if no batch is running.",
)
async def batch_status():
    """Current batch progress, if any."""
    status = batch_status_dict()
    if status is None:
        return {"status": "idle"}
    return status


@router.post(
    "/batch/cancel",
    operation_id="cancel_benchmark_batch",
    summary="Cancel benchmark batch",
    description="Request cancellation of the running batch (skips remaining runs).",
)
async def batch_cancel():
    """Request cancellation of the running batch (skips remaining runs)."""
    status = batch_status_dict()
    if status and status.get("current_run_id"):
        await cancel_run_controller(status["current_run_id"])
    return cancel_batch() or {"status": "idle"}


class SuiteOut(BaseModel):
    id: int
    name: str
    category: str
    runner_class: str

    model_config = {"from_attributes": True}


@router.get(
    "/suites",
    operation_id="list_benchmark_suites",
    summary="List benchmark suites",
    description="Return all registered benchmark suites (speed, coding, tool_use, reasoning).",
    response_model=list[SuiteOut],
)
async def list_suites(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BenchmarkSuite))
    return result.scalars().all()
