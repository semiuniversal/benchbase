"""Sequential benchmark batch runner (all active models × all suites)."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

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
class BatchState:
    batch_id: str
    status: str  # running | completed | cancelled
    total: int
    completed: int = 0
    failed: int = 0
    current_run_id: int | None = None
    current_label: str | None = None
    run_ids: list[int] = field(default_factory=list)


_state: BatchState | None = None
_task: asyncio.Task | None = None


_batch_estimate: dict[str, Any] | None = None


def get_batch_state() -> BatchState | None:
    return _state


def is_batch_running() -> bool:
    return _state is not None and _state.status == "running"


def batch_status_dict() -> dict[str, Any] | None:
    if _state is None:
        return None
    out = {
        "batch_id": _state.batch_id,
        "status": _state.status,
        "total": _state.total,
        "completed": _state.completed,
        "failed": _state.failed,
        "current_run_id": _state.current_run_id,
        "current_label": _state.current_label,
        "run_ids": _state.run_ids,
    }
    if _batch_estimate:
        out["estimate_label"] = _batch_estimate.get("estimate_label")
        out["per_model_label"] = _batch_estimate.get("per_model_label")
    return out


async def start_batch() -> dict[str, Any]:
    global _state, _task, _batch_estimate

    if is_batch_running():
        raise RuntimeError("A benchmark batch is already running")

    factory = get_session_factory()
    async with factory() as db:
        models_result = await db.execute(
            select(Model).where(Model.is_active == True).order_by(Model.name)
        )
        models = models_result.scalars().all()
        suites_result = await db.execute(
            select(BenchmarkSuite).order_by(BenchmarkSuite.id)
        )
        suites = suites_result.scalars().all()

    if not models:
        raise RuntimeError("No active models. Discover and health-check models first.")
    if not suites:
        raise RuntimeError("No benchmark suites configured.")

    queue: list[tuple[int, int, str, str]] = []
    for model in models:
        for suite in suites:
            queue.append((model.id, suite.id, model.name, suite.name))

    settings = load_settings()
    runner_classes = [s.runner_class for s in suites]
    _batch_estimate = estimate_batch_duration(
        len(models),
        settings.batch_sample_limit,
        runner_classes,
    )

    _state = BatchState(
        batch_id=uuid.uuid4().hex[:12],
        status="running",
        total=len(queue),
    )
    _task = asyncio.create_task(_run_batch(queue))
    return batch_status_dict() or {}


def cancel_batch() -> dict[str, Any] | None:
    global _state
    if _state and _state.status == "running":
        _state.status = "cancelled"
    return batch_status_dict()


async def _run_batch(queue: list[tuple[int, int, str, str]]) -> None:
    global _state
    factory = get_session_factory()

    for model_id, suite_id, model_name, suite_name in queue:
        if _state is None or _state.status == "cancelled":
            break

        label = f"{model_name} · {suite_name}"
        _state.current_label = label

        async with factory() as db:
            suite = await db.get(BenchmarkSuite, suite_id)
            if not suite:
                logger.warning("Suite %d missing, skipping", suite_id)
                _state.completed += 1
                continue

            runner_cls = runner_registry.get(suite.runner_class)
            if not runner_cls:
                logger.warning("Unknown runner %s, skipping", suite.runner_class)
                _state.completed += 1
                continue

            run = Run(
                model_id=model_id,
                suite_id=suite_id,
                status=RunStatus.PENDING,
                metadata_json=json.dumps(
                    build_run_metadata("batch", suite.runner_class, load_settings())
                ),
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)

            run.status = RunStatus.RUNNING
            run.started_at = datetime.datetime.now(datetime.UTC)
            await db.commit()

            run_id = run.id
            _state.current_run_id = run_id
            _state.run_ids.append(run_id)

        run_task = asyncio.create_task(execute_run(run_id, runner_cls))
        register_task(run_id, run_task)
        try:
            await run_task
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception("Batch run #%d crashed: %s", run_id, exc)

        async with factory() as db:
            refreshed = await db.get(Run, run_id)
            if refreshed and refreshed.status == RunStatus.FAILED:
                _state.failed += 1

        _state.completed += 1
        _state.current_run_id = None
        _state.current_label = None

    if _state and _state.status == "running":
        _state.status = "completed"
    _state.current_run_id = None
    _state.current_label = None
