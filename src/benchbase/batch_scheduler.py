"""Global benchmark run queue — parallel across models, serial axes within a model."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from benchbase.benchmark_duration import estimate_batch_duration
from benchbase.benchmark_sampling import build_run_metadata
from benchbase.config import load_settings
from benchbase.db.models import BenchmarkAxis, BenchmarkSuite, Model, ModelStatus, Run, RunStatus, RunTier
from benchbase.db.session import get_session_factory
from benchbase.run_controller import register_task
from benchbase.run_executor import execute_run
from benchbase.runners.registry import runner_registry

logger = logging.getLogger(__name__)

# Axis order for a tier run (smoke first, then quality, speed last).
_TIER_AXIS_ORDER = [
    BenchmarkAxis.SMOKE,
    BenchmarkAxis.KNOWLEDGE,
    BenchmarkAxis.REASONING,
    BenchmarkAxis.MATH,
    BenchmarkAxis.CODING,
    BenchmarkAxis.TOOL_CALLING,
    BenchmarkAxis.INSTRUCTION,
    BenchmarkAxis.STRUCTURED,
    BenchmarkAxis.LONG_CONTEXT,
    BenchmarkAxis.SPEED,
]

DEFAULT_MODEL_CONCURRENCY = 2


@dataclass
class BatchJob:
    batch_id: str
    model_id: int
    model_name: str
    run_ids: list[int]
    run_group_id: str
    tier: str
    status: str = "queued"  # queued | running | completed | cancelled
    failed: int = 0


@dataclass
class CurrentRunInfo:
    run_id: int
    model_id: int
    model_name: str
    label: str
    run_group_id: str | None = None
    tier: str | None = None


@dataclass
class QueueState:
    status: str  # idle | running
    current_run_id: int | None = None
    current_label: str | None = None
    pending_count: int = 0
    current_runs: list[CurrentRunInfo] = field(default_factory=list)


_batch_jobs: list[BatchJob] = []
_queue_state = QueueState(status="idle")
_worker_task: asyncio.Task | None = None
_batch_estimate: dict[str, Any] | None = None
_cancelled_batch_ids: set[str] = set()
_abort_wipe_groups: set[str] = set()
_active_tasks: dict[int, asyncio.Task] = {}  # run_id -> task


def get_batch_state() -> QueueState:
    return _queue_state


def is_batch_running() -> bool:
    return _queue_state.status == "running"


def is_queue_active() -> bool:
    return _worker_task is not None and not _worker_task.done()


def mark_batch_cancelled(batch_id: str) -> None:
    """Mark a batch cancelled so remaining pending axes are skipped."""
    _cancelled_batch_ids.add(batch_id)
    for job in _batch_jobs:
        if job.batch_id == batch_id:
            job.status = "cancelled"
            _abort_wipe_groups.add(job.run_group_id)


def cancel_batch() -> None:
    """Cancel the active batch and skip its remaining queued runs."""
    active = _active_batch_job()
    if active:
        mark_batch_cancelled(active.batch_id)


async def wait_runs_not_running(run_ids: list[int], timeout: float = 120.0) -> None:
    """Wait until listed runs are no longer RUNNING (or timeout)."""
    deadline = asyncio.get_event_loop().time() + timeout
    factory = get_session_factory()
    while asyncio.get_event_loop().time() < deadline:
        async with factory() as db:
            still = False
            for rid in run_ids:
                run = await db.get(Run, rid)
                if run and run.status == RunStatus.RUNNING:
                    still = True
                    break
            if not still:
                return
        await asyncio.sleep(0.25)


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
    """Queue a pending run for execution."""
    await _ensure_worker()


def _model_concurrency() -> int:
    settings = load_settings()
    return max(1, int(getattr(settings, "batch_model_concurrency", DEFAULT_MODEL_CONCURRENCY) or DEFAULT_MODEL_CONCURRENCY))


async def start_batch(model_id: int, tier: str = "standard", smoke_override: bool = False) -> dict[str, Any]:
    """Queue a full tier run (all axes) for one active model."""
    try:
        run_tier = RunTier(tier)
    except ValueError as exc:
        raise RuntimeError("tier must be smoke|standard|thorough") from exc

    factory = get_session_factory()
    async with factory() as db:
        model = await db.get(Model, model_id)
        if not model:
            raise RuntimeError("Model not found")
        if model.status != ModelStatus.ACTIVE:
            raise RuntimeError(f"Model {model.name!r} is not active (status={model.status})")

        if run_tier != RunTier.SMOKE and not smoke_override:
            smoke_ok = await _has_passing_smoke(db, model_id)
            if not smoke_ok:
                raise RuntimeError(
                    "Standard/Thorough require a passing Smoke run for this model "
                    "(or pass smoke_override=true)."
                )

        model_name = model.name

    from benchbase.litellm_probe import probe_sticky_min_tokens
    from benchbase.litellm_client import LiteLLMClient

    probe = await probe_sticky_min_tokens(LiteLLMClient(), model_name)
    if probe.get("sticky_min_tokens"):
        raise RuntimeError(
            "LiteLLM quality route has sticky min_tokens — fix proxy extra_body before "
            f"launching {tier!r}. {probe.get('detail', '')}"
        )
    if not probe.get("ok"):
        raise RuntimeError(
            f"LiteLLM quality-route probe failed for {model_name!r}: {probe.get('detail', '')}"
        )

    factory = get_session_factory()
    async with factory() as db:
        model = await db.get(Model, model_id)
        if not model:
            raise RuntimeError("Model not found")

        suites_result = await db.execute(select(BenchmarkSuite))
        suites = list(suites_result.scalars().all())
        by_axis = {s.axis: s for s in suites}
        ordered = [by_axis[a] for a in _TIER_AXIS_ORDER if a in by_axis]

    if not ordered:
        raise RuntimeError("No benchmark suites configured.")

    settings = load_settings()
    runner_classes = [s.runner_class for s in ordered]
    global _batch_estimate
    _batch_estimate = estimate_batch_duration(1, settings.batch_sample_limit, runner_classes)

    batch_id = uuid.uuid4().hex[:12]
    run_group_id = f"tier-{batch_id}"
    run_ids: list[int] = []

    config_snapshot = {
        "model_name": model.name,
        "base_model": model.base_model,
        "quantization": model.quantization,
        "endpoint_url": model.endpoint_url,
        "tier": run_tier.value,
        "smoke_override": smoke_override,
    }
    suite_versions = {s.axis.value: s.suite_version for s in ordered}

    async with factory() as db:
        for suite in ordered:
            runner_cls = runner_registry.get(suite.runner_class)
            if not runner_cls:
                logger.warning("Unknown runner %s, skipping", suite.runner_class)
                continue

            meta = build_run_metadata("batch", suite.runner_class, settings)
            meta["batch_id"] = batch_id
            meta["batch_model_id"] = model_id
            meta["batch_model_name"] = model.name
            meta["tier"] = run_tier.value

            run = Run(
                model_id=model_id,
                suite_id=suite.id,
                run_group_id=run_group_id,
                tier=run_tier,
                status=RunStatus.PENDING,
                smoke_override=smoke_override,
                config_json=json.dumps(config_snapshot),
                suite_versions_json=json.dumps(suite_versions),
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
            run_group_id=run_group_id,
            tier=run_tier.value,
        )
    )
    await _refresh_pending_count()
    await _ensure_worker()
    return await batch_status_dict()


async def _has_passing_smoke(db, model_id: int) -> bool:
    result = await db.execute(
        select(Run)
        .where(
            Run.model_id == model_id,
            Run.status == RunStatus.COMPLETED,
            Run.tier == RunTier.SMOKE,
        )
        .options(selectinload(Run.results), selectinload(Run.suite))
        .order_by(Run.id.desc())
        .limit(20)
    )
    for run in result.scalars().all():
        if not run.suite or run.suite.axis != BenchmarkAxis.SMOKE:
            continue
        # Only count smoke from a fully completed smoke group (no incomplete siblings).
        if run.run_group_id and not await _group_fully_completed(db, run.run_group_id):
            continue
        for res in run.results:
            if res.task_name.startswith("smoke:") and res.score is not None and res.score >= 60:
                return True
    return False


async def _group_fully_completed(db, run_group_id: str) -> bool:
    result = await db.execute(select(Run).where(Run.run_group_id == run_group_id))
    members = list(result.scalars().all())
    if not members:
        return False
    return all(m.status == RunStatus.COMPLETED for m in members)


async def shutdown_queue() -> None:
    """Stop the worker without cancelling in-flight runs."""
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    for task in list(_active_tasks.values()):
        task.cancel()
    _active_tasks.clear()
    _queue_state.status = "idle"
    _queue_state.current_run_id = None
    _queue_state.current_label = None
    _queue_state.current_runs = []


def clear_queue_state() -> None:
    """Reset in-memory queue tracking after all runs are deleted."""
    global _batch_jobs, _batch_estimate, _cancelled_batch_ids, _abort_wipe_groups
    _batch_jobs = []
    _batch_estimate = None
    _cancelled_batch_ids = set()
    _abort_wipe_groups = set()
    _queue_state.status = "idle"
    _queue_state.current_run_id = None
    _queue_state.current_label = None
    _queue_state.pending_count = 0
    _queue_state.current_runs = []
    _active_tasks.clear()


async def batch_status_dict() -> dict[str, Any]:
    await _refresh_pending_count()
    currents = list(_queue_state.current_runs)
    if _queue_state.status == "idle" and _queue_state.pending_count == 0 and not currents:
        paused_job = next((j for j in reversed(_batch_jobs) if j.status == "paused"), None)
        if paused_job is None:
            return {"status": "idle", "pending_count": 0, "current_runs": []}
        completed = 0
        paused_run_id = None
        for rid in paused_job.run_ids:
            status = await _run_terminal_status(rid)
            if status in ("completed", "failed", "cancelled"):
                completed += 1
            elif status == "paused":
                paused_run_id = rid
        return {
            "status": "paused",
            "pending_count": 0,
            "current_runs": [],
            "batch_id": paused_job.batch_id,
            "model_name": paused_job.model_name,
            "total": len(paused_job.run_ids),
            "completed": completed,
            "failed": paused_job.failed,
            "run_ids": paused_job.run_ids,
            "run_group_id": paused_job.run_group_id,
            "tier": paused_job.tier,
            "axes_done": completed,
            "axes_total": len(paused_job.run_ids),
            "paused_run_id": paused_run_id,
        }

    primary = currents[0] if currents else None
    out: dict[str, Any] = {
        "status": "running" if currents or _queue_state.pending_count else "idle",
        "pending_count": _queue_state.pending_count,
        "current_run_id": primary.run_id if primary else _queue_state.current_run_id,
        "current_label": primary.label if primary else _queue_state.current_label,
        "current_runs": [
            {
                "run_id": c.run_id,
                "model_id": c.model_id,
                "model_name": c.model_name,
                "label": c.label,
                "run_group_id": c.run_group_id,
                "tier": c.tier,
            }
            for c in currents
        ],
        "model_concurrency": _model_concurrency(),
    }

    if currents:
        c0 = currents[0]
        names = " · ".join(c.model_name for c in currents)
        out["model_name"] = names if len(currents) > 1 else c0.model_name
        out["run_group_id"] = c0.run_group_id
        out["tier"] = c0.tier
        if c0.run_group_id:
            axes_done, axes_total = await _group_progress(c0.run_group_id)
            out["axes_done"] = axes_done
            out["axes_total"] = axes_total
            out["completed"] = axes_done
            out["total"] = axes_total
    else:
        active = _active_batch_job()
        if active:
            completed = 0
            paused_run_id = None
            for rid in active.run_ids:
                status = await _run_terminal_status(rid)
                if status in ("completed", "failed", "cancelled"):
                    completed += 1
                elif status == "paused":
                    paused_run_id = rid
            out.update(
                {
                    "status": "paused" if active.status == "paused" or paused_run_id else out["status"],
                    "batch_id": active.batch_id,
                    "model_name": active.model_name,
                    "total": len(active.run_ids),
                    "completed": completed,
                    "failed": active.failed,
                    "run_ids": active.run_ids,
                    "run_group_id": active.run_group_id,
                    "tier": active.tier,
                    "axes_done": completed,
                    "axes_total": len(active.run_ids),
                    "paused_run_id": paused_run_id,
                }
            )
        elif _batch_jobs:
            next_job = next((j for j in _batch_jobs if j.status == "queued"), None)
            if next_job:
                out["queued_model_name"] = next_job.model_name
                out["queued_total"] = len(next_job.run_ids)
                out["run_group_id"] = next_job.run_group_id
                out["tier"] = next_job.tier

    if _batch_estimate:
        out["estimate_label"] = _batch_estimate.get("estimate_label")
        out["per_model_label"] = _batch_estimate.get("per_model_label")
    return out


async def _group_progress(run_group_id: str) -> tuple[int, int]:
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(Run).where(Run.run_group_id == run_group_id))
        members = list(result.scalars().all())
    total = len(members)
    done = sum(1 for m in members if m.status.value in ("completed", "failed", "cancelled"))
    return done, total


def _active_batch_job() -> BatchJob | None:
    for job in reversed(_batch_jobs):
        if job.status in ("running", "queued", "paused"):
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


def _busy_model_ids() -> set[int]:
    return {c.model_id for c in _queue_state.current_runs}


async def _prior_group_axes_terminal(db, run: Run) -> bool:
    """True if every earlier run in the same group (lower id) is terminal."""
    if not run.run_group_id:
        return True
    result = await db.execute(
        select(Run).where(
            Run.run_group_id == run.run_group_id,
            Run.id < run.id,
        )
    )
    priors = list(result.scalars().all())
    terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
    return all(p.status in terminal for p in priors)


async def _pick_next_run(db) -> Run | None:
    """Pick next pending run respecting per-model serial axes and concurrency slots."""
    result = await db.execute(
        select(Run)
        .where(Run.status == RunStatus.PENDING)
        .order_by(Run.id)
    )
    pending = list(result.scalars().all())
    busy = _busy_model_ids()
    for run in pending:
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
            continue
        if run.model_id in busy:
            continue
        if not await _prior_group_axes_terminal(db, run):
            continue
        return run
    await db.commit()
    return None


def _track_current(info: CurrentRunInfo) -> None:
    """Reserve a model slot immediately so concurrent picks see it as busy."""
    if any(c.run_id == info.run_id for c in _queue_state.current_runs):
        return
    _queue_state.current_runs.append(info)
    _queue_state.current_run_id = info.run_id
    _queue_state.current_label = info.label


def _untrack_current(run_id: int) -> None:
    _queue_state.current_runs = [c for c in _queue_state.current_runs if c.run_id != run_id]
    if _queue_state.current_runs:
        head = _queue_state.current_runs[0]
        _queue_state.current_run_id = head.run_id
        _queue_state.current_label = head.label
    else:
        _queue_state.current_run_id = None
        _queue_state.current_label = None


async def _execute_one(run_id: int, runner_cls, batch_id: str | None, info: CurrentRunInfo) -> None:
    # Slot already reserved by _fill_slots via _track_current(info).
    try:
        run_task = asyncio.create_task(execute_run(run_id, runner_cls))
        _active_tasks[run_id] = run_task
        register_task(run_id, run_task)
        try:
            await run_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception("Queued run #%d crashed: %s", run_id, exc)
    finally:
        _active_tasks.pop(run_id, None)
        _untrack_current(run_id)

        factory = get_session_factory()
        async with factory() as db:
            refreshed = await db.get(Run, run_id)
            if refreshed and batch_id:
                for job in _batch_jobs:
                    if job.batch_id != batch_id:
                        continue
                    if refreshed.status == RunStatus.FAILED:
                        job.failed += 1
                    if refreshed.status == RunStatus.PAUSED:
                        job.status = "paused"
                        break
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


async def _fill_slots(factory, inflight: set[asyncio.Task]) -> int:
    """Schedule as many eligible pending runs as concurrency allows. Returns count started."""
    started = 0
    while True:
        slots = _model_concurrency() - len(_queue_state.current_runs)
        if slots <= 0:
            break
        async with factory() as db:
            run = await _pick_next_run(db)
            if not run:
                break

            meta: dict[str, Any] = {}
            if run.metadata_json:
                try:
                    meta = json.loads(run.metadata_json)
                except json.JSONDecodeError:
                    pass
            batch_id = meta.get("batch_id")

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
            if run.started_at is None:
                run.started_at = datetime.datetime.now(datetime.UTC)
            await db.commit()

            info = CurrentRunInfo(
                run_id=run.id,
                model_id=run.model_id,
                model_name=model.name,
                label=f"{model.name} · {suite.name}",
                run_group_id=run.run_group_id,
                tier=run.tier.value if run.tier else None,
            )
            # Reserve the slot before yielding so the next pick sees this model as busy.
            _track_current(info)
            run_id = run.id

        task = asyncio.create_task(_execute_one(run_id, runner_cls, batch_id, info))
        inflight.add(task)
        started += 1
        logger.info(
            "Scheduled run #%d (%s); in_flight_models=%d/%d",
            run_id,
            info.label,
            len(_queue_state.current_runs),
            _model_concurrency(),
        )
        await _refresh_pending_count()
    return started


async def _worker_loop() -> None:
    global _worker_task
    factory = get_session_factory()
    _queue_state.status = "running"
    inflight: set[asyncio.Task] = set()

    try:
        while True:
            await _refresh_pending_count()
            # Reap finished tasks
            done = {t for t in inflight if t.done()}
            for t in done:
                try:
                    t.result()
                except Exception:
                    pass
            inflight -= done

            if _queue_state.pending_count == 0 and not inflight:
                break

            await _fill_slots(factory, inflight)

            if not inflight:
                # Pending exists but blocked (e.g. waiting on prior axis) — wait briefly.
                if _queue_state.pending_count > 0:
                    await asyncio.sleep(0.5)
                    continue
                break

            # Timeout so newly queued models can claim free concurrency slots while
            # other models are mid-axis (previously we blocked until FIRST_COMPLETED).
            await asyncio.wait(
                inflight,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=0.5,
            )
    finally:
        _queue_state.status = "idle"
        _queue_state.current_run_id = None
        _queue_state.current_label = None
        _queue_state.current_runs = []
        _worker_task = None
        await _refresh_pending_count()
