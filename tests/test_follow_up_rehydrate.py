"""Smoke → Standard follow-up survives worker restart (in-memory job loss)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from benchbase.batch_scheduler import (
    BatchJob,
    _follow_up_from_config,
    _rehydrate_smoke_follow_up_watchers,
    clear_queue_state,
)
from benchbase.db.models import (
    BenchmarkAxis,
    BenchmarkSuite,
    Model,
    ModelStatus,
    Run,
    RunStatus,
    RunTier,
)


def test_follow_up_from_config_parses_json():
    cfg = json.dumps({"follow_up_tier": "standard", "tier": "smoke"})
    assert _follow_up_from_config(cfg) == "standard"
    assert _follow_up_from_config(None) is None


@pytest.fixture
async def session_factory(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from benchbase.db.models import Base

    db_path = tmp_path / "rehydrate.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("BENCHBASE_DB_URL", url)
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_rehydrate_restores_smoke_job_after_clear(session_factory, monkeypatch):
    clear_queue_state()
    async with session_factory() as db:
        model = Model(
            name="rehydrate-model",
            endpoint_url="http://127.0.0.1/v1",
            status=ModelStatus.ACTIVE.value,
            is_active=True,
            color="blue",
            context_window_manual=False,
            supports_vision=False,
        )
        db.add(model)
        suite = BenchmarkSuite(
            name="Smoke",
            axis=BenchmarkAxis.SMOKE,
            category=BenchmarkAxis.SMOKE,
            runner_class="smoke",
            suite_version="v2",
        )
        db.add(suite)
        await db.flush()
        group_id = "tier-rehydrate-test"
        cfg = json.dumps({"follow_up_tier": "standard", "tier": "smoke"})
        meta = json.dumps({"batch_id": "batch-rehydrate"})
        run = Run(
            model_id=model.id,
            suite_id=suite.id,
            run_group_id=group_id,
            tier=RunTier.SMOKE,
            status=RunStatus.PENDING,
            config_json=cfg,
            metadata_json=meta,
        )
        db.add(run)
        await db.commit()

    from benchbase.db import session as db_session_mod

    monkeypatch.setattr(db_session_mod, "get_session_factory", lambda: session_factory)
    await _rehydrate_smoke_follow_up_watchers(session_factory)
    from benchbase import batch_scheduler

    assert any(
        j.run_group_id == group_id and j.follow_up_tier == "standard"
        for j in batch_scheduler._batch_jobs
    )
    clear_queue_state()