"""Global benchmark run queue — one run at a time, multi-model queuing."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from benchbase.benchmark_duration import estimate_batch_duration
from benchbase.benchmark_sampling import build_run_metadata
from benchbase.config import load_settings
from benchbase.db.models import BenchmarkSuite, Model, Run, RunStatus
from benchbase.db.session import get_session_factory
from benchbase.run_controller import register_task
from benchbase.run_executor import execute_run
from benchbase.runners.registry import runner_registry

logger = logging.getLogger(__name__)


@dataclass
class BatchJob:
    batch_id: str
    model_id: int
    model_name: str
    run_ids: list[int]
    status: str = "queued"  # queued | running | completed | cancelled
    failed: int = 0


@dataclass
class QueueState:
    status: str  # idle | running
    current_run_id: int | None = None
    current_label: str | None = None
    pending_count: int = 0


_batch_jobs: list[BatchJob] = []
_queue_state = QueueState(status="idle")
_worker_task: asyncio.Task | None = None
_batch_estimate: dict[str, Any] | None = None
_cancelled_batch_ids: set[str] = set()


def get_batch_state() -> QueueState:
    return _queue_state


def is_batch_running() -> bool:
    return _queue_state.status == "running"


def is_queue_active() -> bool:
    return _worker_task is not None and not _worker_task.done()


async def resume_queue() -> None:
    """Resume processing pending runs after server start."""
    factory = get_session_factory()
    async with factory() as db:
        count = await db.scalar(
            select(func.count()).select_from(Run).where(Run.status == RunStatus.PENDING)
        )
    if count:
        await _ensure_worker()


async def enqueue_run(run_id: int) -> None:
    """Queue a pending run for sequential execution."""
    await _ensure_worker()


async def start_batch(model_id: int) -> dict[str, Any]:
    """Queue all benchmark suites for one model."""
    factory = get_session_factory()
    async with factory() as db:
        model = await db.get(Model, model_id)
        if not model:
            raise RuntimeError("Model not found")
        if not model.is_active:
            raise RuntimeError(f"Model {model.name!r} is inactive")

        suites_result = await db.execute(
            select(BenchmarkSuite).order_by(BenchmarkSuite.id)
        )
        suites = suites_result.scalars().all()

    if not suites:
        raise RuntimeError("No benchmark suites configured.")

    settings = load_settings()
    runner_classes = [s.runner_class for s in suites]
    global _batch_estimate
    _batch_estimate = estimate_batch_duration(1, settings.batch_sample_limit, runner_classes)

    batch_id = uuid.uuid4().hex[:12]
    run_ids: list[int] = []

    async with factory() as db:
        for suite in suites:
            runner_cls = runner_registry.get(suite.runner_class)
            if not runner_cls:
                logger.warning("Unknown runner %s, skipping", suite.runner_class)
                continue

            meta = build_run_metadata("batch", suite.runner_class, settings)
            meta["batch_id"] = batch_id
            meta["batch_model_id"] = model_id
            meta["batch_model_name"] = model.name

            run = Run(
                model_id=model_id,
                suite_id=suite.id,
                status=RunStatus.PENDING,
                metadata_json=json.dumps(meta),
            )
            db.add(run)
            await db.flush()
            run_ids.append(run.id)
        await db.commit()

    if not run_ids:
        raise RuntimeError("No runnable suites found.")

    _batch_jobs.append(
        BatchJob(
            batch_id=batch_id,
            model_id=model_id,
            model_name=model.name,
            run_ids=run_ids,
        )
    )
    await _refresh_pending_count()
    await _ensure_worker()
    return await batch_status_dict()


def cancel_batch() -> None:
    """Cancel the active batch and skip its remaining queued runs."""
    active = _active_batch_job()
    if active:
        active.status = "cancelled"
        _cancelled_batch_ids.add(active.batch_id)


async def shutdown_queue() -> None:
    """Stop the worker without cancelling in-flight runs."""
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    _queue_state.status = "idle"
    _queue_state.current_run_id = None
    _queue_state.current_label = None


def clear_queue_state() -> None:
    """Reset in-memory queue tracking after all runs are deleted."""
    global _batch_jobs, _batch_estimate, _cancelled_batch_ids
    _batch_jobs = []
    _batch_estimate = None
    _cancelled_batch_ids = set()
    _queue_state.status = "idle"
    _queue_state.current_run_id = None
    _queue_state.current_label = None
    _queue_state.pending_count = 0


async def batch_status_dict() -> dict[str, Any]:
    await _refresh_pending_count()
    if _queue_state.status == "idle" and _queue_state.pending_count == 0:
        return {"status": "idle", "pending_count": 0}

    active = _active_batch_job()
    out: dict[str, Any] = {
        "status": _queue_state.status if _queue_state.pending_count else "idle",
        "pending_count": _queue_state.pending_count,
        "current_run_id": _queue_state.current_run_id,
        "current_label": _queue_state.current_label,
    }

    if active:
        completed = 0
        for rid in active.run_ids:
            status = await _run_terminal_status(rid)
            if status in ("completed", "failed", "cancelled"):
                completed += 1
        out.update(
            {
                "batch_id": active.batch_id,
                "model_name": active.model_name,
                "total": len(active.run_ids),
                "completed": completed,
                "failed": active.failed,
                "run_ids": active.run_ids,
            }
        )
    elif _batch_jobs:
        next_job = next((j for j in _batch_jobs if j.status == "queued"), None)
        if next_job:
            out["queued_model_name"] = next_job.model_name
            out["queued_total"] = len(next_job.run_ids)

    if _batch_estimate:
        out["estimate_label"] = _batch_estimate.get("estimate_label")
        out["per_model_label"] = _batch_estimate.get("per_model_label")
    return out


def _active_batch_job() -> BatchJob | None:
    for job in reversed(_batch_jobs):
        if job.status in ("running", "queued"):
            return job
    return None


async def _run_terminal_status(run_id: int) -> str | None:
    factory = get_session_factory()
    async with factory() as db:
        run = await db.get(Run, run_id)
        if not run:
            return None
        return run.status.value


async def _refresh_pending_count() -> None:
    factory = get_session_factory()
    async with factory() as db:
        count = await db.scalar(
            select(func.count()).select_from(Run).where(Run.status == RunStatus.PENDING)
        )
    _queue_state.pending_count = int(count or 0)


async def _ensure_worker() -> None:
    global _worker_task
    if _worker_task is None or _worker_task.done():
        _worker_task = asyncio.create_task(_worker_loop())


async def _worker_loop() -> None:
    global _worker_task
    factory = get_session_factory()
    _queue_state.status = "running"

    try:
        while True:
            await _refresh_pending_count()
            if _queue_state.pending_count == 0:
                break

            async with factory() as db:
                result = await db.execute(
                    select(Run)
                    .where(Run.status == RunStatus.PENDING)
                    .order_by(Run.id)
                    .limit(1)
                )
                run = result.scalar_one_or_none()
                if not run:
                    break

                meta: dict[str, Any] = {}
                if run.metadata_json:
                    try:
                        meta = json.loads(run.metadata_json)
                    except json.JSONDecodeError:
                        pass

                batch_id = meta.get("batch_id")
                if batch_id and batch_id in _cancelled_batch_ids:
                    run.status = RunStatus.CANCELLED
                    run.completed_at = datetime.datetime.now(datetime.UTC)
                    await db.commit()
                    continue

                suite = await db.get(BenchmarkSuite, run.suite_id)
                model = await db.get(Model, run.model_id)
                if not suite or not model:
                    run.status = RunStatus.FAILED
                    run.completed_at = datetime.datetime.now(datetime.UTC)
                    await db.commit()
                    continue

                runner_cls = runner_registry.get(suite.runner_class)
                if not runner_cls:
                    run.status = RunStatus.FAILED
                    run.completed_at = datetime.datetime.now(datetime.UTC)
                    await db.commit()
                    continue

                if batch_id:
                    for job in _batch_jobs:
                        if job.batch_id == batch_id and job.status == "queued":
                            job.status = "running"
                            break

                run.status = RunStatus.RUNNING
                run.started_at = datetime.datetime.now(datetime.UTC)
                await db.commit()

                run_id = run.id
                label = f"{model.name} · {suite.name}"
                _queue_state.current_run_id = run_id
                _queue_state.current_label = label

            run_task = asyncio.create_task(execute_run(run_id, runner_cls))
            register_task(run_id, run_task)
            try:
                await run_task
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Queued run #%d crashed: %s", run_id, exc)

            async with factory() as db:
                refreshed = await db.get(Run, run_id)
                if refreshed and batch_id:
                    for job in _batch_jobs:
                        if job.batch_id == batch_id:
                            if refreshed.status == RunStatus.FAILED:
                                job.failed += 1
                            all_done = True
                            for rid in job.run_ids:
                                status = await _run_terminal_status(rid)
                                if status not in ("completed", "failed", "cancelled"):
                                    all_done = False
                                    break
                            if all_done:
                                job.status = (
                                    "cancelled"
                                    if batch_id in _cancelled_batch_ids
                                    else "completed"
                                )
                            break

            _queue_state.current_run_id = None
            _queue_state.current_label = None
    finally:
        _queue_state.status = "idle"
        _queue_state.current_run_id = None
        _queue_state.current_label = None
        _worker_task = None
        await _refresh_pending_count()
