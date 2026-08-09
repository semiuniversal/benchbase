"""Tests for atomic tier run-group delete / abort semantics."""

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
    Run,
    RunStatus,
    RunTier,
)
from benchbase.run_groups import abort_run_group, delete_run_group


async def _run_delete_test(db_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        model = Model(
            name="test-model-group",
            endpoint_url="http://localhost:4000",
            status=ModelStatus.ACTIVE,
            color="blue",
        )
        db_session.add(model)
        await db_session.flush()

        suites = []
        for axis in [BenchmarkAxis.SMOKE, BenchmarkAxis.KNOWLEDGE]:
            s = BenchmarkSuite(
                name=f"Suite {axis.value}",
                category=axis,
                axis=axis,
                runner_class=axis.value,
                suite_version="v2",
            )
            db_session.add(s)
            suites.append(s)
        await db_session.flush()

        gid = "tier-testabort01"
        runs = []
        for suite in suites:
            run = Run(
                model_id=model.id,
                suite_id=suite.id,
                run_group_id=gid,
                tier=RunTier.STANDARD,
                status=RunStatus.COMPLETED,
            )
            db_session.add(run)
            await db_session.flush()
            db_session.add(
                Result(run_id=run.id, task_name=f"{suite.axis.value}:t", score=80.0, n_items=10)
            )
            runs.append(run)
        await db_session.commit()

        deleted = await delete_run_group(db_session, gid)
        assert deleted == 2
        left = list(await db_session.scalars(select(Run).where(Run.run_group_id == gid)))
        assert left == []
        left_results = list(
            await db_session.scalars(
                select(Result).where(Result.run_id.in_([r.id for r in runs]))
            )
        )
        assert left_results == []
    await engine.dispose()


async def _run_abort_test(db_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        model = Model(
            name="test-model-abort",
            endpoint_url="http://localhost:4000",
            status=ModelStatus.ACTIVE,
            color="teal",
        )
        db_session.add(model)
        await db_session.flush()

        suites = []
        for axis in [BenchmarkAxis.KNOWLEDGE, BenchmarkAxis.MATH, BenchmarkAxis.CODING]:
            s = BenchmarkSuite(
                name=f"Suite {axis.value}",
                category=axis,
                axis=axis,
                runner_class=axis.value,
                suite_version="v2",
            )
            db_session.add(s)
            suites.append(s)
        await db_session.flush()

        gid = "tier-testabort02"
        r0 = Run(
            model_id=model.id,
            suite_id=suites[0].id,
            run_group_id=gid,
            tier=RunTier.STANDARD,
            status=RunStatus.COMPLETED,
        )
        db_session.add(r0)
        await db_session.flush()
        db_session.add(
            Result(run_id=r0.id, task_name="knowledge:tiny_mmlu", score=90.0, n_items=100)
        )
        for suite in suites[1:]:
            db_session.add(
                Run(
                    model_id=model.id,
                    suite_id=suite.id,
                    run_group_id=gid,
                    tier=RunTier.STANDARD,
                    status=RunStatus.PENDING,
                )
            )
        await db_session.commit()

        out = await abort_run_group(db_session, gid)
        assert out["aborted"] is True
        assert out["deleted"] == 3
        left = list(await db_session.scalars(select(Run).where(Run.run_group_id == gid)))
        assert left == []
    await engine.dispose()


def test_delete_run_group_removes_all_siblings():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run_delete_test(Path(tmp) / "a.db"))


def test_abort_pending_group_wipes_completed_siblings():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_run_abort_test(Path(tmp) / "b.db"))
