"""Benchmark run management routes."""

from __future__ import annotations

import asyncio
import datetime
import json

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.benchmark_duration import estimate_run_duration
from benchbase.benchmark_sampling import build_run_metadata
from benchbase.batch_scheduler import (
    batch_status_dict,
    cancel_batch,
    clear_queue_state,
    enqueue_run,
    resume_queue,
    shutdown_queue,
    start_batch,
)
from benchbase.db.models import BenchmarkSuite, Model, Result, ResultItem, Run, RunStatus
from benchbase.db.session import get_db
from benchbase.run_controller import cancel_run as cancel_run_controller, clear_cancelled, reset_run_tracking
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
    ci_low: float | None = None
    ci_high: float | None = None
    n_items: int | None = None
    metrics: dict | None = None


class RunOut(BaseModel):
    id: int
    model_id: int
    suite_id: int
    status: str
    tier: str | None = None
    run_group_id: str | None = None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    results: list[ResultSummary] = []
    harness_version: str | None = None
    suite_version: str | None = None
    omp_provider: str | None = None
    omp_model: str | None = None
    display_label: str | None = None

    model_config = {"from_attributes": True}


def _parse_run_config(run: Run) -> dict:
    raw = {}
    if run.config_json:
        try:
            parsed = json.loads(run.config_json)
            if isinstance(parsed, dict):
                raw = parsed
        except json.JSONDecodeError:
            pass
    if run.metadata_json:
        try:
            meta = json.loads(run.metadata_json)
            if isinstance(meta, dict):
                raw = {**raw, **meta}
        except json.JSONDecodeError:
            pass
    return raw


def _run_to_out(run: Run, results: list[Result] | None = None) -> RunOut:
    res = results if results is not None else []
    cfg = _parse_run_config(run)
    result_summaries: list[ResultSummary] = []
    display_label = None
    for r in res:
        metrics = None
        if getattr(r, "metrics_json", None):
            try:
                metrics = json.loads(r.metrics_json) if r.metrics_json else None
            except json.JSONDecodeError:
                metrics = None
        if isinstance(metrics, dict) and metrics.get("display") and not display_label:
            display_label = str(metrics.get("display"))
        result_summaries.append(
            ResultSummary(
                task_name=r.task_name,
                score=r.score,
                ci_low=getattr(r, "ci_low", None),
                ci_high=getattr(r, "ci_high", None),
                n_items=getattr(r, "n_items", None),
                metrics=metrics if isinstance(metrics, dict) else None,
            )
        )
    harness = cfg.get("harness_version")
    suite_ver = cfg.get("suite_version")
    omp_provider = cfg.get("omp_provider")
    omp_model = cfg.get("omp_model")
    if not display_label and (harness or suite_ver):
        display_label = (
            f"Finalist · Agentic · {suite_ver or '?'} · OMP {harness or '?'} · run #{run.id}"
        )
    elif display_label and f"run #{run.id}" not in display_label:
        display_label = f"{display_label} · run #{run.id}"
    return RunOut(
        id=run.id,
        model_id=run.model_id,
        suite_id=run.suite_id,
        status=run.status.value,
        tier=run.tier.value if getattr(run, "tier", None) else None,
        run_group_id=getattr(run, "run_group_id", None),
        started_at=run.started_at,
        completed_at=run.completed_at,
        results=result_summaries,
        harness_version=str(harness) if harness else None,
        suite_version=str(suite_ver) if suite_ver else None,
        omp_provider=str(omp_provider) if omp_provider else None,
        omp_model=str(omp_model) if omp_model else None,
        display_label=display_label,
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
async def list_runs(
    model_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Run).options(selectinload(Run.results)).order_by(Run.id.desc()).limit(200)
    if model_id is not None:
        stmt = (
            select(Run)
            .where(Run.model_id == model_id)
            .options(selectinload(Run.results))
            .order_by(Run.id.desc())
            .limit(200)
        )
    result = await db.execute(stmt)
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
    "/runs",
    operation_id="delete_all_benchmark_runs",
    summary="Delete all benchmark runs",
    description="Remove every run and result. Blocked while a run is in progress.",
)
async def delete_all_runs(db: AsyncSession = Depends(get_db)):
    running = await db.scalar(
        select(func.count()).select_from(Run).where(Run.status == RunStatus.RUNNING)
    )
    if running:
        raise HTTPException(400, "Cannot clear benchmarks while a run is in progress.")

    await shutdown_queue()

    run_ids = list(await db.scalars(select(Run.id)))
    for run_id in run_ids:
        RunLogManager.remove(run_id)
        reset_run_tracking(run_id)

    await db.execute(delete(ResultItem))
    await db.execute(delete(Result))
    await db.execute(delete(Run))
    await db.commit()
    clear_queue_state()
    return {"deleted": len(run_ids)}


@router.delete(
    "/run-groups/{run_group_id}",
    operation_id="delete_benchmark_run_group",
    summary="Delete a tier run set",
    description="Delete every axis run in a Smoke/Standard/Thorough set.",
)
async def delete_run_group_route(run_group_id: str, db: AsyncSession = Depends(get_db)):
    from benchbase.run_groups import delete_run_group, list_group_runs

    runs = await list_group_runs(db, run_group_id)
    if not runs:
        raise HTTPException(404, "Run group not found")
    if any(r.status == RunStatus.RUNNING for r in runs):
        raise HTTPException(400, "Group has a running member; abort instead of delete.")
    try:
        deleted = await delete_run_group(db, run_group_id)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"deleted": deleted, "run_group_id": run_group_id}


@router.post(
    "/run-groups/{run_group_id}/abort",
    operation_id="abort_benchmark_run_group",
    summary="Stop and discard a tier run set",
    description=(
        "Cancel the in-flight axis, skip remaining axes, and delete the entire set "
        "so partial results never enter the scorecard."
    ),
)
async def abort_run_group_route(run_group_id: str, db: AsyncSession = Depends(get_db)):
    from benchbase.run_groups import abort_run_group, list_group_runs

    runs = await list_group_runs(db, run_group_id)
    if not runs:
        raise HTTPException(404, "Run group not found")
    return await abort_run_group(db, run_group_id)


@router.delete(
    "/runs/{run_id}",
    operation_id="delete_benchmark_run",
    summary="Delete a benchmark run",
    description=(
        "If the run belongs to a tier set (run_group_id), deletes the entire set. "
        "Cannot delete while a member is running — use abort."
    ),
)
async def delete_run(run_id: int, db: AsyncSession = Depends(get_db)):
    from benchbase.run_groups import delete_run_group, delete_run_ids

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.run_group_id:
        runs = (
            await db.execute(select(Run).where(Run.run_group_id == run.run_group_id))
        ).scalars().all()
        if any(r.status == RunStatus.RUNNING for r in runs):
            raise HTTPException(400, "Cannot delete while running; abort the tier set instead.")
        deleted = await delete_run_group(db, run.run_group_id)
        return {"deleted": True, "deleted_count": deleted, "run_group_id": run.run_group_id}

    if run.status == RunStatus.RUNNING:
        raise HTTPException(400, "Cannot delete a run that is still in progress")
    await delete_run_ids(db, [run_id])
    return {"deleted": True, "deleted_count": 1}


@router.post(
    "/runs/{run_id}/cancel",
    operation_id="cancel_benchmark_run",
    summary="Cancel a benchmark run",
    description=(
        "If the run is part of a tier set, aborts and discards the entire set. "
        "Otherwise cancels only that run."
    ),
)
async def cancel_run(run_id: int, db: AsyncSession = Depends(get_db)):
    """Stop a running benchmark; tier sets wipe the whole group."""
    from benchbase.run_groups import abort_run_group

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.run_group_id:
        return await abort_run_group(db, run.run_group_id)
    if run.status != RunStatus.RUNNING:
        raise HTTPException(400, f"Run is not running (status: {run.status.value})")

    stopped = await cancel_run_controller(run_id)
    RunLogManager.log(run_id, "Cancellation requested…")

    if not stopped:
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

    runner_cls = runner_registry.get(run.suite.runner_class)
    if not runner_cls:
        raise HTTPException(400, f"Unknown runner: {run.suite.runner_class}")

    reset_run_tracking(run_id)

    await enqueue_run(run_id)
    pending = run.status == RunStatus.PENDING
    return {"status": "queued" if pending else "running"}


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


def _parse_agentic_item_id(item_id: str) -> tuple[str, int]:
    if ":seed" not in item_id:
        raise HTTPException(400, "item_id must look like task:seedN")
    task_id, _, seed_s = item_id.rpartition(":seed")
    try:
        return task_id, int(seed_s)
    except ValueError as exc:
        raise HTTPException(400, "invalid seed in item_id") from exc


@router.get(
    "/runs/{run_id}/agentic/current",
    operation_id="get_agentic_current_attempt",
    summary="Current agentic attempt pointer",
)
async def agentic_current(run_id: int, db: AsyncSession = Depends(get_db)):
    from benchbase.agentic.session_store import read_current

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return {"current": read_current(run_id)}


@router.get(
    "/runs/{run_id}/agentic/attempts",
    operation_id="list_agentic_attempts",
    summary="List agentic attempts for a run",
)
async def list_agentic_attempts(run_id: int, db: AsyncSession = Depends(get_db)):
    from benchbase.agentic.session_store import (
        list_transcript_files,
        parse_item_id_from_filename,
        read_current,
        transcript_relpath,
    )
    from benchbase.db.models import Result, ResultItem

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    detail_by_item: dict[str, dict] = {}
    passed_by_item: dict[str, bool] = {}
    items_result = await db.execute(
        select(ResultItem)
        .join(Result, ResultItem.result_id == Result.id)
        .where(Result.run_id == run_id)
    )
    for row in items_result.scalars().all():
        passed_by_item[row.item_id] = bool(row.passed)
        if row.detail_json:
            try:
                detail_by_item[row.item_id] = json.loads(row.detail_json)
            except json.JSONDecodeError:
                detail_by_item[row.item_id] = {}

    attempts: list[dict] = []
    seen: set[str] = set()
    for path in list_transcript_files(run_id):
        parsed = parse_item_id_from_filename(path.name)
        if not parsed:
            continue
        task_id, seed = parsed
        iid = f"{task_id}:seed{seed}"
        seen.add(iid)
        detail = detail_by_item.get(iid) or {}
        attempts.append(
            {
                "item_id": iid,
                "task_id": task_id,
                "seed": seed,
                "transcript_exists": True,
                "transcript_path": transcript_relpath(run_id, task_id, seed),
                "passed": passed_by_item.get(iid),
                "fixture": detail.get("fixture"),
                "instruction": detail.get("instruction"),
                "tool_calls": detail.get("tool_calls"),
                "turns": detail.get("turns"),
                "wall_seconds": detail.get("wall_seconds"),
            }
        )
    for iid, detail in detail_by_item.items():
        if iid in seen:
            continue
        task_id, seed = _parse_agentic_item_id(iid)
        attempts.append(
            {
                "item_id": iid,
                "task_id": task_id,
                "seed": seed,
                "transcript_exists": False,
                "transcript_path": detail.get("transcript_path"),
                "passed": passed_by_item.get(iid),
                "fixture": detail.get("fixture"),
                "instruction": detail.get("instruction"),
                "tool_calls": detail.get("tool_calls"),
                "turns": detail.get("turns"),
                "wall_seconds": detail.get("wall_seconds"),
            }
        )
    attempts.sort(key=lambda a: (a["task_id"], a["seed"]))
    return {"attempts": attempts, "current": read_current(run_id)}


@router.get(
    "/runs/{run_id}/agentic/attempts/{item_id}/transcript",
    operation_id="get_agentic_attempt_transcript",
    summary="Get normalized agentic attempt transcript",
)
async def get_agentic_transcript(
    run_id: int, item_id: str, db: AsyncSession = Depends(get_db)
):
    from benchbase.agentic.session_store import (
        normalize_events,
        read_raw_events,
        transcript_abspath,
    )

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    task_id, seed = _parse_agentic_item_id(item_id)
    path = transcript_abspath(run_id, task_id, seed)
    if not path.is_file():
        raise HTTPException(404, "Transcript not found")
    raw = read_raw_events(path)
    return {
        "item_id": item_id,
        "task_id": task_id,
        "seed": seed,
        "path": str(path),
        "events": normalize_events(raw),
        "raw_count": len(raw),
    }


@router.get(
    "/runs/{run_id}/agentic/attempts/{item_id}/events",
    operation_id="stream_agentic_attempt_events",
    summary="Stream agentic attempt events (SSE)",
)
async def stream_agentic_events(
    run_id: int, item_id: str, db: AsyncSession = Depends(get_db)
):
    from benchbase.agentic.session_store import (
        AttemptEventBus,
        normalize_events,
        read_raw_events,
        transcript_abspath,
    )

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    task_id, seed = _parse_agentic_item_id(item_id)
    path = transcript_abspath(run_id, task_id, seed)

    async def event_generator():
        # Replay what is already on disk
        if path.is_file():
            raw = read_raw_events(path)
            for turn in normalize_events(raw):
                yield {"event": "turn", "data": json.dumps(turn)}
        buffer = AttemptEventBus.get(run_id, item_id)
        if buffer is None:
            # Wait briefly for attempt to start
            for _ in range(60):
                await asyncio.sleep(0.5)
                buffer = AttemptEventBus.get(run_id, item_id)
                if buffer is not None or (path.is_file() and run.status.value != "running"):
                    break
        if buffer is None:
            yield {"event": "done", "data": json.dumps({"status": "complete"})}
            return
        seen = 0
        if path.is_file():
            seen = len(read_raw_events(path))
        async for entry in buffer.subscribe():
            # Prefer normalized single-event views
            for turn in normalize_events([entry.raw]):
                yield {"event": "turn", "data": json.dumps(turn)}
            seen += 1
        yield {"event": "done", "data": json.dumps({"status": "complete"})}

    return EventSourceResponse(event_generator())


@router.get(
    "/runs/{run_id}/agentic/attempts/{item_id}/workspace",
    operation_id="get_agentic_attempt_workspace",
    summary="List fixture workspace tree for an attempt",
)
async def get_agentic_workspace(
    run_id: int, item_id: str, db: AsyncSession = Depends(get_db)
):
    from benchbase.agentic.session_store import read_current
    from benchbase.agentic.workspace_view import list_fixture_tree, resolve_fixture_for_item
    from benchbase.db.models import Result, ResultItem

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    task_id, seed = _parse_agentic_item_id(item_id)
    fixture = None
    instruction = None
    row = await db.execute(
        select(ResultItem)
        .join(Result, ResultItem.result_id == Result.id)
        .where(Result.run_id == run_id, ResultItem.item_id == item_id)
    )
    item = row.scalar_one_or_none()
    if item and item.detail_json:
        try:
            detail = json.loads(item.detail_json)
            fixture = detail.get("fixture")
            instruction = detail.get("instruction")
        except json.JSONDecodeError:
            pass
    if not fixture:
        cur = read_current(run_id)
        if cur and cur.get("item_id") == item_id:
            fixture = cur.get("fixture")
            instruction = instruction or cur.get("instruction")
    if not fixture:
        cfg = {}
        if run.config_json:
            try:
                cfg = json.loads(run.config_json)
            except json.JSONDecodeError:
                pass
        fixture = resolve_fixture_for_item(task_id, cfg.get("suite_version"))
    if not fixture:
        raise HTTPException(404, "Could not resolve fixture for attempt")
    try:
        tree = list_fixture_tree(str(fixture))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "item_id": item_id,
        "task_id": task_id,
        "seed": seed,
        "fixture": fixture,
        "instruction": instruction,
        "tree": tree,
    }


@router.get(
    "/runs/{run_id}/agentic/attempts/{item_id}/workspace/file",
    operation_id="get_agentic_attempt_workspace_file",
    summary="Read a fixture file for an attempt workspace",
)
async def get_agentic_workspace_file(
    run_id: int,
    item_id: str,
    path: str,
    db: AsyncSession = Depends(get_db),
):
    from benchbase.agentic.session_store import read_current
    from benchbase.agentic.workspace_view import read_fixture_file, resolve_fixture_for_item
    from benchbase.db.models import Result, ResultItem

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    task_id, _seed = _parse_agentic_item_id(item_id)
    fixture = None
    row = await db.execute(
        select(ResultItem)
        .join(Result, ResultItem.result_id == Result.id)
        .where(Result.run_id == run_id, ResultItem.item_id == item_id)
    )
    item = row.scalar_one_or_none()
    if item and item.detail_json:
        try:
            fixture = json.loads(item.detail_json).get("fixture")
        except json.JSONDecodeError:
            pass
    if not fixture:
        cur = read_current(run_id)
        if cur and cur.get("item_id") == item_id:
            fixture = cur.get("fixture")
    if not fixture:
        cfg = {}
        if run.config_json:
            try:
                cfg = json.loads(run.config_json)
            except json.JSONDecodeError:
                pass
        fixture = resolve_fixture_for_item(task_id, cfg.get("suite_version"))
    if not fixture:
        raise HTTPException(404, "Could not resolve fixture")
    try:
        content = read_fixture_file(str(fixture), path)
    except PermissionError as exc:
        raise HTTPException(400, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"path": path, "content": content, "fixture": fixture}


class BatchStart(BaseModel):
    model_id: int = Field(description="Database ID of the model to run.")
    tier: Literal["smoke", "standard", "thorough"] = Field(
        default="standard",
        description="Run tier — the only launchable unit in v2.",
    )
    smoke_override: bool = Field(
        default=False,
        description="Allow Standard/Thorough without a passing Smoke run.",
    )


@router.post(
    "/batch/start",
    operation_id="start_benchmark_batch",
    summary="Start tier run",
    description="Queue a full Smoke/Standard/Thorough tier for one active model.",
)
async def batch_start(body: BatchStart):
    """Queue a tier run (all axes for that tier)."""
    try:
        return await start_batch(
            body.model_id, tier=body.tier, smoke_override=body.smoke_override
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.get(
    "/batch/status",
    operation_id="get_benchmark_batch_status",
    summary="Get benchmark batch status",
    description="Current batch progress, or idle if no batch is running.",
)
async def batch_status():
    """Current queue progress, if any."""
    status = await batch_status_dict()
    if status.get("status") == "idle" and not status.get("pending_count"):
        return {"status": "idle", "pending_count": 0}
    return status


@router.post(
    "/batch/cancel",
    operation_id="cancel_benchmark_batch",
    summary="Cancel benchmark batch",
    description="Abort and discard the active tier set (all axes).",
)
async def batch_cancel(db: AsyncSession = Depends(get_db)):
    """Abort the active batch's run group so partial results are wiped."""
    from benchbase.run_groups import abort_run_group

    status = await batch_status_dict()
    group_id = status.get("run_group_id")
    if group_id:
        result = await abort_run_group(db, group_id)
        cleared = await batch_status_dict()
        return {**cleared, **result}
    if status.get("current_run_id"):
        await cancel_run_controller(status["current_run_id"])
    cancel_batch()
    cleared = await batch_status_dict()
    if cleared.get("status") == "idle" and not cleared.get("pending_count"):
        return {"status": "idle", "pending_count": 0}
    return cleared


class SuiteOut(BaseModel):
    id: int
    name: str
    category: str
    axis: str | None = None
    runner_class: str
    suite_version: str | None = None
    content_hash: str | None = None
    scorer_status: str | None = None

    model_config = {"from_attributes": True}


class AgenticStart(BaseModel):
    model_id: int = Field(description="Database ID of the model / deployment to evaluate.")
    suite_version: Literal["mvp", "headline"] = Field(
        default="mvp",
        description="mvp = 8 tasks × n_seeds; headline = ~20 tasks × n_seeds.",
    )
    n_seeds: int | None = Field(
        default=None,
        description="Override seeds (default mvp=3, headline=5).",
        ge=1,
        le=8,
    )
    task_ids: list[str] | None = Field(
        default=None,
        description="Optional subset of task ids.",
    )
    mock: bool = Field(
        default=False,
        description="Use fixture transcript + synthetic resolutions (CI / no OMP).",
    )
    package_hash: str | None = Field(
        default=None,
        description="Deployment package hash placeholder until estimator store exists.",
    )
    omp_provider: Literal["litellm", "openrouter"] | None = Field(
        default=None,
        description="OMP provider id. Use openrouter for instrument validation (DeepSeek Flash).",
    )
    omp_model: str | None = Field(
        default=None,
        description="OMP --model slug override (e.g. deepseek/deepseek-v4-flash-0731).",
    )
    instrument_validation: bool = Field(
        default=False,
        description=(
            "Harness proof: remote OpenRouter model acts as the agent under test "
            "(not interlocutor/judge). Not a local UUT score."
        ),
    )


@router.post(
    "/agentic/start",
    operation_id="start_agentic_finalist",
    summary="Start Finalist · Agentic run",
    description=(
        "Dedicated finalist path (not Smoke/Standard/Thorough). Forces concurrency=1. "
        "Requires sole tenancy on the inference host — see doc/agentic-sole-tenancy.md."
    ),
)
async def start_agentic(body: AgenticStart, db: AsyncSession = Depends(get_db)):
    from benchbase.batch_scheduler import batch_status_dict, enqueue_run
    from benchbase.db.models import BenchmarkAxis, ModelStatus, RunTier

    model = await db.get(Model, body.model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    if model.status != ModelStatus.ACTIVE:
        raise HTTPException(400, f"Model {model.name!r} is not active")

    if not body.instrument_validation:
        from benchbase.model_eligibility import model_finalist_eligible

        if not await model_finalist_eligible(db, body.model_id):
            raise HTTPException(
                409,
                "Finalist requires a completed Standard (or Thorough) tier for this model. "
                "Run Standard first, or use Instrument validation for harness proof.",
            )

    status = await batch_status_dict()
    if status.get("status") == "running" or status.get("pending_count", 0) > 0:
        raise HTTPException(
            409,
            "Queue busy — agentic runs require concurrency=1 / sole tenancy. "
            "Finish or cancel other benchmarks first.",
        )

    result = await db.execute(
        select(BenchmarkSuite).where(BenchmarkSuite.axis == BenchmarkAxis.AGENTIC)
    )
    suite = result.scalar_one_or_none()
    if not suite:
        raise HTTPException(500, "Agentic suite not seeded — restart API after upgrade")

    n_seeds = body.n_seeds
    if n_seeds is None:
        n_seeds = 3 if body.suite_version == "mvp" else 5

    omp_provider = body.omp_provider
    omp_model = body.omp_model
    if body.instrument_validation:
        omp_provider = omp_provider or "openrouter"
        omp_model = omp_model or "deepseek/deepseek-v4-flash-0731"

    meta = {
        "suite_version": body.suite_version,
        "n_seeds": n_seeds,
        "task_ids": body.task_ids,
        "mock": body.mock,
        "package_hash": body.package_hash or "placeholder-until-estimator-store",
        "concurrency": 1,
        "sole_tenancy": True,
        "finalist": True,
        "instrument_validation": body.instrument_validation,
    }
    if omp_provider:
        meta["omp_provider"] = omp_provider
    if omp_model:
        meta["omp_model"] = omp_model
    run = Run(
        model_id=body.model_id,
        suite_id=suite.id,
        status=RunStatus.PENDING,
        tier=RunTier.THOROUGH,  # longest track; not a tier-batch member
        metadata_json=json.dumps(meta),
        config_json=json.dumps(meta),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    reset_run_tracking(run.id)
    await enqueue_run(run.id)
    return {
        "status": "queued",
        "run_id": run.id,
        "suite_version": body.suite_version,
        "n_seeds": n_seeds,
        "concurrency": 1,
        "omp_provider": omp_provider,
        "omp_model": omp_model,
        "instrument_validation": body.instrument_validation,
        "display_label": (
            f"Finalist · Agentic · {body.suite_version}"
            + (" · instrument" if body.instrument_validation or omp_provider == "openrouter" else "")
            + f" · run #{run.id}"
        ),
    }


@router.get(
    "/suites",
    operation_id="list_benchmark_suites",
    summary="List benchmark suites",
    description="Return all registered benchmark suites (v2 quality axes + speed + smoke).",
    response_model=list[SuiteOut],
)
async def list_suites(db: AsyncSession = Depends(get_db)):
    from benchbase.controls import get_scorer_status_map

    result = await db.execute(select(BenchmarkSuite))
    suites = result.scalars().all()
    status_map = await get_scorer_status_map(db)
    out = []
    for s in suites:
        axis = s.axis.value if s.axis else None
        if axis == "agentic":
            scorer = "n/a"
        elif axis:
            scorer = status_map.get(axis or "", "unknown")
        else:
            scorer = "valid"
        out.append(
            SuiteOut(
                id=s.id,
                name=s.name,
                category=s.category.value if s.category else (axis or ""),
                axis=axis,
                runner_class=s.runner_class,
                suite_version=s.suite_version,
                content_hash=s.content_hash,
                scorer_status=scorer,
            )
        )
    return out


@router.post(
    "/controls/run",
    operation_id="run_scoring_controls",
    summary="Run null/random/echo scoring controls",
)
async def run_scoring_controls(
    tier: str = "standard",
    db: AsyncSession = Depends(get_db),
):
    from benchbase.controls import run_controls
    from benchbase.db.models import RunTier

    try:
        run_tier = RunTier(tier)
    except ValueError as exc:
        raise HTTPException(400, "tier must be smoke|standard|thorough") from exc
    return await run_controls(db, tier=run_tier)


@router.get(
    "/controls/status",
    operation_id="scoring_controls_status",
    summary="Scorer validity status from control bounds",
)
async def scoring_controls_status(db: AsyncSession = Depends(get_db)):
    from benchbase.controls import evaluate_control_bounds, get_scorer_status_map

    status = await get_scorer_status_map(db)
    if any(v == "unknown" for k, v in status.items() if k != "speed"):
        report = await evaluate_control_bounds(db)
        return {"status": status, "report": report}
    return {"status": status}
