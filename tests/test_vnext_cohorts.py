"""WP1: smoke-only models excluded from standard_completed Borda pool."""

from __future__ import annotations

import asyncio

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
from benchbase.scoring import _build_scorecards


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db_session_factory(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    engine = create_async_engine(url)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    factory = _run(setup())
    yield factory
    _run(engine.dispose())


def _result(score: float, task: str = "knowledge:v2") -> Result:
    return Result(
        task_name=task,
        score=score,
        n_items=100,
        metrics_json='{"successes": 90, "planned_n": 100}',
    )


def test_smoke_only_not_in_standard_cohort(db_session_factory):
    async def body():
        async with db_session_factory() as db:
            model = Model(
                name="smoke-only",
                endpoint_url="http://127.0.0.1",
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
                status=RunStatus.COMPLETED,
                tier=RunTier.SMOKE,
                run_group_id="g-smoke",
            )
            db.add(run)
            await db.flush()
            results = [_result(95.0)]
            for r in results:
                r.run_id = run.id
            await db.commit()

            models_data = {
                "smoke-only": {
                    "model_name": "smoke-only",
                    "best_tier": "smoke",
                    "suite_versions": {"knowledge": "v2"},
                    "axis_runs": {"knowledge": results},
                    "all_results": results,
                }
            }
            cards = _build_scorecards(
                models_data,
                {"knowledge": "v2"},
                {"knowledge": "ok"},
                work_clocks={},
                ranking_cohort="standard_completed",
            )
            assert cards[0]["cohort_eligible"] is False
            assert cards[0]["overall_rank"] is None

    _run(body())


def test_arena_metrics_provider_usage():
    from benchbase.metrics.arena_stream import ArenaStreamAccumulator

    acc = ArenaStreamAccumulator()
    acc.note_chunk("content")
    acc.note_chunk("content")
    acc.note_usage({"completion_tokens": 40})
    snap = acc.snapshot()
    assert snap["decode_rate_method"] == "provider_usage"
    assert snap["output_tokens"] == 40
    assert snap["output_chunk_rate_per_s"] is not None