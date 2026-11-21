"""WP3: checkpoint_item writes evidence observation."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.db.models import (
    Base,
    BenchmarkAxis,
    BenchmarkSuite,
    EvidenceObservation,
    Model,
    ModelStatus,
    Result,
    Run,
    RunStatus,
    RunTier,
)
from benchbase.runners.quality_common import checkpoint_item, ensure_axis_result


@pytest.fixture
def db_factory(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    engine = create_async_engine(url)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    factory = asyncio.run(setup())
    yield factory
    asyncio.run(engine.dispose())


def test_checkpoint_creates_evidence_row(db_factory, tmp_path, monkeypatch):
    import benchbase.config as cfg

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    import benchbase.evidence.store as estore

    monkeypatch.setattr(estore, "DATA_DIR", tmp_path)

    async def body():
        async with db_factory() as db:
            model = Model(
                name="m1",
                endpoint_url="http://127.0.0.1",
                color="blue",
                status=ModelStatus.ACTIVE,
            )
            suite = BenchmarkSuite(
                name="K",
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
                tier=RunTier.STANDARD,
            )
            db.add(run)
            await db.flush()
            result = await ensure_axis_result(
                db,
                run,
                task_name="knowledge:v2",
                planned_n=10,
            )
            row = {
                "item_id": "k-001",
                "passed": True,
                "raw_answer": "B",
                "latency_ms": 12.0,
            }
            await checkpoint_item(db, result, row, commit=True)
            obs = (await db.execute(select(EvidenceObservation))).scalars().all()
            assert len(obs) == 1
            assert obs[0].item_id == "k-001"

    asyncio.run(body())