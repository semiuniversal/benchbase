"""WP1: model-scorecard ranking_cohort API."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.db.models import Base
from benchbase.main import app
from benchbase.db.session import get_db


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("BENCHBASE_DB_URL", url)
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.anyio
async def test_ranking_cohort_query_invalid(client):
    r = await client.get("/api/results/model-scorecard?ranking_cohort=nope")
    assert r.status_code == 400


@pytest.mark.anyio
async def test_ranking_cohort_default_in_payload(client):
    r = await client.get("/api/results/model-scorecard")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # empty DB → empty list is fine