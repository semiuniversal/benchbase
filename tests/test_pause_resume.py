"""Pause / resume / checkpoint regressions for quality axes."""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.db.models import (
    Base,
    BenchmarkAxis,
    BenchmarkSuite,
    Model,
    ModelStatus,
    ResultItem,
    Run,
    RunStatus,
    RunTier,
)
from benchbase.run_controller import (
    clear_pause,
    is_pause_requested,
    request_pause,
    reset_run_tracking,
)
from benchbase.runners.quality_common import (
    ensure_axis_result,
    finalize_axis_result,
    is_infra_error,
    load_completed_item_ids,
    run_quality_items,
)
from benchbase.scoring import _build_scorecards
from benchbase.work_clock import AxisWall, Sitting, suite_wall_s


def _run_async(coro):
    return asyncio.run(coro)


@pytest.fixture
def db_session():
    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite+aiosqlite:///{Path(tmp) / 't.db'}"
        engine = create_async_engine(url)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async def setup():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            return Session

        session_factory = _run_async(setup())
        yield session_factory
        _run_async(engine.dispose())


async def _seed_run(db):
    model = Model(
        name="seat-pause",
        endpoint_url="http://127.0.0.1:9",
        color="blue",
        status=ModelStatus.ACTIVE,
    )
    suite = BenchmarkSuite(
        name="Knowledge",
        axis=BenchmarkAxis.KNOWLEDGE,
        category=BenchmarkAxis.KNOWLEDGE,
        runner_class="knowledge",
        suite_version="v2",
    )
    db.add_all([model, suite])
    await db.flush()
    run = Run(
        model_id=model.id,
        suite_id=suite.id,
        status=RunStatus.RUNNING,
        tier=RunTier.SMOKE,
        run_group_id="tier-pause-test",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()
    return run


def test_is_infra_error_detects_transport():
    assert is_infra_error(httpx.ConnectError("connection refused"))
    assert is_infra_error(RuntimeError("Connection refused to LiteLLM"))
    assert not is_infra_error(ValueError("bad parse"))


def test_checkpoint_and_resume_skips_done(db_session):
    async def body():
        reset_run_tracking(1)
        async with db_session() as db:
            run = await _seed_run(db)
            items = [{"item_id": f"i{i}", "n": i} for i in range(5)]
            calls: list[str] = []

            async def score_one(item):
                calls.append(item["item_id"])
                if item["item_id"] == "i2" and len(calls) == 3:
                    request_pause(run.id)
                return {
                    "item_id": item["item_id"],
                    "passed": True,
                    "latency_ms": 10.0,
                }

            outcome, result = await run_quality_items(
                db, run, "knowledge:tiny_mmlu", items, score_one, title="Knowledge"
            )
            assert outcome == "paused"
            assert is_pause_requested(run.id)
            done = await load_completed_item_ids(db, result)
            assert done == {"i0", "i1", "i2"}
            assert result.score is None

            clear_pause(run.id)
            calls.clear()
            outcome2, result2 = await run_quality_items(
                db, run, "knowledge:tiny_mmlu", items, score_one, title="Knowledge"
            )
            assert outcome2 == "completed"
            assert set(calls) == {"i3", "i4"}
            assert result2.n_items == 5
            assert result2.score == pytest.approx(100.0)
            metrics = json.loads(result2.metrics_json)
            assert metrics["planned_n"] == 5
            assert metrics["successes"] == 5

    _run_async(body())


def test_auto_pause_on_infra_does_not_fail_items(db_session):
    async def body():
        reset_run_tracking(1)
        async with db_session() as db:
            run = await _seed_run(db)
            items = [{"item_id": f"i{i}"} for i in range(4)]

            async def score_one(item):
                if item["item_id"] in {"i1", "i2", "i3"}:
                    raise httpx.ConnectError("connection refused")
                return {"item_id": item["item_id"], "passed": True, "latency_ms": 5.0}

            outcome, result = await run_quality_items(
                db,
                run,
                "knowledge:tiny_mmlu",
                items,
                score_one,
                infra_pause_after=2,
            )
            assert outcome == "paused"
            done = await load_completed_item_ids(db, result)
            assert done == {"i0"}
            from sqlalchemy import select

            rows = list(
                (await db.execute(select(ResultItem).where(ResultItem.result_id == result.id)))
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].passed is True

    _run_async(body())


def test_paused_group_excluded_from_borda():
    cards = _build_scorecards(
        {
            "seat": {
                "model_name": "seat",
                "suite_versions": {},
                "all_results": [],
                "axis_runs": {},
                "work_clock_group": "g-paused",
                "has_benchmark_history": True,
            }
        },
        {a: "v2" for a in (
            "knowledge", "reasoning", "math", "coding", "tool_calling",
            "instruction", "structured", "long_context",
        )},
        {a: "valid" for a in (
            "knowledge", "reasoning", "math", "coding", "tool_calling",
            "instruction", "structured", "long_context",
        )},
        work_clocks={},
    )
    assert cards[0]["borda_score"] == 0
    assert cards[0]["overall_rank"] is None


def test_suite_wall_prefers_active_ms():
    now = datetime.now(timezone.utc)
    sitting = Sitting(
        run_group_id="g1",
        model_id=1,
        model_name="seat",
        tier="standard",
        axes={
            axis: AxisWall(
                axis,
                i,
                "completed",
                now - timedelta(hours=2),
                now,
                10,
                active_ms=5_000.0,
            )
            for i, axis in enumerate(
                [
                    "knowledge",
                    "reasoning",
                    "math",
                    "coding",
                    "tool_calling",
                    "instruction",
                    "structured",
                    "long_context",
                ]
            )
        },
    )
    wall = suite_wall_s(sitting)
    assert wall == pytest.approx(40.0)
    # Legacy fallback without active_ms would be ~2h * 8.
    legacy = Sitting(
        run_group_id="g2",
        model_id=1,
        model_name="seat",
        tier="standard",
        axes={
            "knowledge": AxisWall(
                "knowledge",
                1,
                "completed",
                now - timedelta(seconds=30),
                now,
                1,
                active_ms=None,
            ),
            **{
                a: AxisWall(a, i + 2, "completed", now - timedelta(seconds=10), now, 1)
                for i, a in enumerate(
                    [
                        "reasoning",
                        "math",
                        "coding",
                        "tool_calling",
                        "instruction",
                        "structured",
                        "long_context",
                    ]
                )
            },
        },
    )
    assert suite_wall_s(legacy) == pytest.approx(100.0)


def test_finalize_counts_checkpointed_items(db_session):
    async def body():
        async with db_session() as db:
            run = await _seed_run(db)
            result = await ensure_axis_result(
                db, run, "coding:livecodebench", planned_n=3
            )
            from benchbase.runners.quality_common import checkpoint_item

            await checkpoint_item(
                db, result, {"item_id": "a", "passed": True}, commit=False
            )
            await checkpoint_item(
                db,
                result,
                {"item_id": "b", "passed": False, "reason": "incorrect"},
                commit=False,
            )
            await checkpoint_item(
                db,
                result,
                {
                    "item_id": "c",
                    "passed": None,
                    "scorer_error": True,
                    "reason": "scorer-error",
                },
                commit=False,
            )
            await finalize_axis_result(db, result)
            await db.commit()
            assert result.n_items == 3
            assert result.score == pytest.approx(33.3)
            m = json.loads(result.metrics_json)
            assert m["successes"] == 1
            assert m["scorer_errors"] == 1

    _run_async(body())


def test_effective_run_status_shows_pausing():
    from benchbase.api.routes.benchmarks import _effective_run_status
    from benchbase.run_controller import clear_pause, request_pause, reset_run_tracking

    reset_run_tracking(42)
    run = Run(
        id=42,
        model_id=1,
        suite_id=1,
        status=RunStatus.RUNNING,
        tier=RunTier.STANDARD,
    )
    assert _effective_run_status(run) == "running"
    request_pause(42)
    assert _effective_run_status(run) == "pausing"
    clear_pause(42)
    run.status = RunStatus.PAUSED
    assert _effective_run_status(run) == "paused"
