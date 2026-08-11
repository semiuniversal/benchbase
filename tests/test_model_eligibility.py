"""Eligibility helpers and model notes / Finalist gate."""

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
    Run,
    RunStatus,
    RunTier,
)
from benchbase.model_eligibility import (
    model_finalist_eligible,
    model_has_completed_tier,
)
from benchbase.litellm_client import LiteLLMClient


def test_extract_model_info_fields():
    info = LiteLLMClient._extract_model_info(
        {
            "supports_vision": True,
            "max_input_tokens": 128000,
            "max_output_tokens": 8192,
            "litellm_provider": "openai",
        },
        {},
    )
    assert info["supports_vision"] is True
    assert info["context_window"] == 128000
    assert info["max_output_tokens"] == 8192
    assert info["raw"]["max_input_tokens"] == 128000


async def _seed(db_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        model = Model(
            name="uut-a",
            endpoint_url="http://127.0.0.1:9",
            color="blue",
        )
        model.set_status(ModelStatus.ACTIVE)
        suite = BenchmarkSuite(
            name="Knowledge",
            axis=BenchmarkAxis.KNOWLEDGE,
            category=BenchmarkAxis.KNOWLEDGE,
            runner_class="knowledge",
            suite_version="v1",
        )
        agentic = BenchmarkSuite(
            name="Finalist · Agentic (OMP)",
            axis=BenchmarkAxis.AGENTIC,
            category=BenchmarkAxis.AGENTIC,
            runner_class="agentic",
            suite_version="mvp",
        )
        db.add_all([model, suite, agentic])
        await db.flush()
        gid = "std-group-1"
        for _ in range(2):
            run = Run(
                model_id=model.id,
                suite_id=suite.id,
                status=RunStatus.COMPLETED,
                tier=RunTier.STANDARD,
                run_group_id=gid,
                metadata_json=json.dumps({"tier": "standard"}),
            )
            db.add(run)
        await db.commit()
        mid = model.id
        assert await model_has_completed_tier(db, mid, RunTier.STANDARD)
        assert await model_finalist_eligible(db, mid)

        # Agentic thorough-tier run must not count as Standard batch.
        other = Model(
            name="uut-b",
            endpoint_url="http://127.0.0.1:9",
            color="cyan",
        )
        other.set_status(ModelStatus.ACTIVE)
        db.add(other)
        await db.flush()
        agentic_run = Run(
            model_id=other.id,
            suite_id=agentic.id,
            status=RunStatus.COMPLETED,
            tier=RunTier.THOROUGH,
            metadata_json=json.dumps({"finalist": True}),
        )
        db.add(agentic_run)
        await db.commit()
        assert not await model_finalist_eligible(db, other.id)
    await engine.dispose()


def test_standard_tier_completion_eligibility():
    with tempfile.TemporaryDirectory() as td:
        asyncio.run(_seed(Path(td) / "t.db"))
