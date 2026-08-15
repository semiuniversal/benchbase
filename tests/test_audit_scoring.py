"""Regression tests for audit scoring fixes (denominator, sitting, coverage, TTFT)."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.db.models import (
    Base,
    BenchmarkAxis,
    BenchmarkSuite,
    Model,
    ModelStatus,
    Result,
    Run,
    RunStatus,
    RunTier,
)
from benchbase.runners.long_context import _bury, _select_items
from benchbase.runners.quality_common import load_fixture_items, persist_axis_result
from benchbase.runners.speed import _resolve_think_time, _resolve_ttft
from benchbase.scoring import _build_scorecards, _extract_axis
from benchbase.work_clock import Sitting, AxisWall, n_correct, pick_sitting


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


def test_persist_scorer_error_stays_in_denominator(db_session):
    async def body():
        async with db_session() as db:
            model = Model(
                name="seat-a",
                endpoint_url="http://127.0.0.1:9",
                color="blue",
                status=ModelStatus.ACTIVE,
            )
            suite = BenchmarkSuite(
                name="Coding",
                axis=BenchmarkAxis.CODING,
                category=BenchmarkAxis.CODING,
                runner_class="coding",
                suite_version="v2",
            )
            db.add_all([model, suite])
            await db.flush()
            run = Run(
                model_id=model.id,
                suite_id=suite.id,
                status=RunStatus.COMPLETED,
                tier=RunTier.STANDARD,
            )
            db.add(run)
            await db.flush()

            planned = 40
            rows = []
            for i in range(11):
                rows.append({"item_id": f"ok_{i}", "passed": True})
            for i in range(29):
                rows.append(
                    {
                        "item_id": f"err_{i}",
                        "passed": None,
                        "scorer_error": True,
                        "reason": "scorer-error",
                    }
                )
            assert len(rows) == planned
            result = await persist_axis_result(
                db, run, "coding:livecodebench", rows
            )
            await db.commit()

            assert result.n_items == planned
            metrics = json.loads(result.metrics_json)
            assert metrics["planned_n"] == planned
            assert metrics["scored_n"] == planned
            assert metrics["successes"] == 11
            assert metrics["scorer_errors"] == 29
            # 11/40 = 27.5 — must not inflate to 100
            assert result.score == pytest.approx(27.5)
            assert result.score < 100.0

    _run_async(body())


def test_extract_axis_exposes_planned_n_and_coverage():
    results = [
        Result(
            run_id=1,
            task_name="coding:livecodebench",
            score=100.0,
            n_items=11,
            metrics_json=json.dumps({"planned_n": 40, "successes": 11}),
        )
    ]
    primary, _, _, _, _, n_items, planned_n = _extract_axis(
        results, {"primary_prefix": "coding:"}
    )
    assert primary == 100.0
    assert n_items == 11
    assert planned_n == 40

    cards = _build_scorecards(
        {
            "seat": {
                "model_name": "seat",
                "suite_versions": {"coding": "v2"},
                "all_results": results,
                "axis_runs": {"coding": results},
                "work_clock_group": "g1",
            }
        },
        {"coding": "v2"},
        {a: "valid" for a in (
            "knowledge", "reasoning", "math", "coding", "tool_calling",
            "instruction", "structured", "long_context",
        )},
        work_clocks={},
    )
    dim = cards[0]["dimensions"]["coding"]
    assert dim["planned_n"] == 40
    assert dim["n_items"] == 11
    assert dim["excluded_from_ranking"] is True
    assert dim["borda_points"] == 0


def test_pick_sitting_prefers_standard_for_axes_unity():
    smoke = Sitting(
        run_group_id="smoke-g",
        model_id=1,
        model_name="seat",
        tier="smoke",
        axes={
            a: AxisWall(a, i, "completed", None, None, 1)
            for i, a in enumerate(
                [
                    "knowledge", "reasoning", "math", "coding",
                    "tool_calling", "instruction", "structured", "long_context",
                ],
                start=1,
            )
        },
    )
    standard = Sitting(
        run_group_id="std-g",
        model_id=1,
        model_name="seat",
        tier="standard",
        axes={
            a: AxisWall(a, 100 + i, "completed", None, None, 50)
            for i, a in enumerate(
                [
                    "knowledge", "reasoning", "math", "coding",
                    "tool_calling", "instruction", "structured", "long_context",
                ]
            )
        },
    )
    chosen = pick_sitting([smoke, standard])
    assert chosen is standard
    assert chosen.run_group_id == "std-g"
    assert n_correct(chosen) == 50 * 8


def test_ttft_not_aliased_to_think_wall():
    thinking = {
        "think_ttft_ms": {"mean": 120.0, "std": 1.0},
        "output_ttft_ms": {"mean": 5000.0, "std": 1.0},
        "think_time_ms": {"mean": 5000.0, "std": 1.0},
        "think_duration_ms": {"mean": 4800.0, "std": 1.0},
    }
    bm: dict = {}
    ttft = _resolve_ttft(thinking, bm)
    think = _resolve_think_time(thinking)
    assert ttft is not None and ttft["mean"] == 120.0
    assert think is not None and think["mean"] == 4800.0
    assert ttft["mean"] != think["mean"]


def test_resolve_think_drops_aliased_wall():
    thinking = {
        "output_ttft_ms": {"mean": 3210.5, "std": 0},
        "think_time_ms": {"mean": 3210.5, "std": 0},
    }
    assert _resolve_think_time(thinking) is None


def test_long_context_v3_loader_and_no_delimiters():
    items = load_fixture_items("long_context", "v3")
    assert len(items) >= 40
    assert all(i.get("kind") in {"niah", "multi_needle", "variable_tracking"} for i in items)
    assert any(i.get("length") == 32000 for i in items)
    assert not any("<<" in json.dumps(i) for i in items)
    buried = _bury("NEEDLE-TEST", 8000, "middle")
    assert "<<" not in buried
    assert "NEEDLE-TEST" in buried
    standard = _select_items(items, RunTier.STANDARD)
    assert {int(i["length"]) for i in standard} == {8000, 16000, 32000}
    smoke = _select_items(items, RunTier.SMOKE)
    assert len(smoke) == 5
    assert all(int(i["length"]) == 8000 for i in smoke)


def test_n_correct_identity_with_axis_successes():
    from benchbase.scoring import _axis_successes_total, _reconcile_work_clock

    axis_runs = {
        "knowledge": [
            Result(
                run_id=1,
                task_name="knowledge:x",
                score=50,
                n_items=100,
                metrics_json=json.dumps({"successes": 50, "planned_n": 100}),
            )
        ],
        "coding": [
            Result(
                run_id=2,
                task_name="coding:x",
                score=25,
                n_items=40,
                metrics_json=json.dumps({"successes": 10, "planned_n": 40}),
            )
        ],
    }
    assert _axis_successes_total(axis_runs) == 60
    clock = {
        "n_correct": 475,
        "sec_per_correct": 1.0,
        "work_clock_group": "std-g",
        "work_clock_index": 100,
    }
    fixed = _reconcile_work_clock(clock, axis_runs, expected_group="std-g")
    assert fixed["n_correct"] == 60
    assert fixed["sec_per_correct"] is None
    assert fixed["invalid_reason"]
