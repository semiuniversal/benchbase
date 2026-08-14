"""Deleting a model must wipe associated runs and results."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.db.models import (
    Base,
    BenchmarkAxis,
    BenchmarkSuite,
    Model,
    ModelStatus,
    Result,
    ResultItem,
    Run,
    RunStatus,
    RunTier,
)
from benchbase.run_groups import delete_model_and_runs


async def _run_delete_model_test(db_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        model = Model(
            name="doomed-model",
            endpoint_url="http://127.0.0.1:9",
            status=ModelStatus.ACTIVE,
            color="blue",
        )
        keep = Model(
            name="keep-model",
            endpoint_url="http://127.0.0.1:9",
            status=ModelStatus.ACTIVE,
            color="teal",
        )
        suite = BenchmarkSuite(
            name="Speed",
            axis=BenchmarkAxis.SPEED,
            category=BenchmarkAxis.SPEED,
            runner_class="speed",
            suite_version="v2",
        )
        db.add_all([model, keep, suite])
        await db.flush()

        doomed_run = Run(
            model_id=model.id,
            suite_id=suite.id,
            tier=RunTier.STANDARD,
            status=RunStatus.COMPLETED,
        )
        keep_run = Run(
            model_id=keep.id,
            suite_id=suite.id,
            tier=RunTier.STANDARD,
            status=RunStatus.COMPLETED,
        )
        db.add_all([doomed_run, keep_run])
        await db.flush()

        result = Result(
            run_id=doomed_run.id, task_name="speed:output_tps2048", score=15.0, n_items=5
        )
        db.add(result)
        await db.flush()
        db.add(
            ResultItem(
                result_id=result.id,
                item_id="tg-0",
                passed=True,
                latency_ms=100.0,
            )
        )
        keep_result = Result(
            run_id=keep_run.id, task_name="speed:output_tps2048", score=70.0, n_items=5
        )
        db.add(keep_result)
        await db.commit()

        doomed_id = model.id
        doomed_run_id = doomed_run.id
        keep_id = keep.id
        keep_run_id = keep_run.id

        out = await delete_model_and_runs(db, doomed_id)
        assert out["deleted"] is True
        assert out["runs_deleted"] == 1

        assert await db.get(Model, doomed_id) is None
        assert list(await db.scalars(select(Run).where(Run.id == doomed_run_id))) == []
        assert list(
            await db.scalars(select(Result).where(Result.run_id == doomed_run_id))
        ) == []
        assert list(
            await db.scalars(select(ResultItem).where(ResultItem.item_id == "tg-0"))
        ) == []

        assert await db.get(Model, keep_id) is not None
        leftover = list(await db.scalars(select(Run).where(Run.id == keep_run_id)))
        assert len(leftover) == 1
        leftover_results = list(
            await db.scalars(select(Result).where(Result.run_id == keep_run_id))
        )
        assert len(leftover_results) == 1
    await engine.dispose()


def test_delete_model_removes_associated_runs():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run_delete_model_test(Path(tmp) / "models.db"))
