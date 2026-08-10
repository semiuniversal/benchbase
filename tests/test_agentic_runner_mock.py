"""CI smoke: agentic runner mock path (1 task × 1 seed, no GPU/OMP)."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.db.models import (
    Base,
    BenchmarkAxis,
    BenchmarkSuite,
    Model,
    ModelStatus,
    Run,
    RunStatus,
    RunTier,
)
from benchbase.runners.agentic import AgenticRunner


async def _run_mock(db_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        model = Model(
            name="mock-model",
            endpoint_url="http://127.0.0.1:9",
            status=ModelStatus.ACTIVE,
            is_active=True,
            color="blue",
        )
        suite = BenchmarkSuite(
            name="Finalist · Agentic (OMP)",
            axis=BenchmarkAxis.AGENTIC,
            category=BenchmarkAxis.AGENTIC,
            runner_class="agentic",
            suite_version="mvp",
        )
        db_session.add_all([model, suite])
        await db_session.flush()
        meta = {
            "suite_version": "mvp",
            "n_seeds": 1,
            "task_ids": ["greet-welcome"],
            "mock": True,
        }
        run = Run(
            model_id=model.id,
            suite_id=suite.id,
            status=RunStatus.RUNNING,
            tier=RunTier.THOROUGH,
            metadata_json=json.dumps(meta),
            config_json=json.dumps(meta),
        )
        db_session.add(run)
        await db_session.commit()

        await AgenticRunner().run(run, db_session)
        await db_session.commit()
        from sqlalchemy import select
        from benchbase.db.models import Result

        rows = (
            await db_session.execute(select(Result).where(Result.run_id == run.id))
        ).scalars().all()
        assert rows
        assert rows[0].task_name == "agentic:mvp"
        assert rows[0].n_items == 1
        assert rows[0].score == 100.0
    await engine.dispose()


def test_agentic_runner_mock_one_task():
    with tempfile.TemporaryDirectory() as td:
        asyncio.run(_run_mock(Path(td) / "t.db"))
