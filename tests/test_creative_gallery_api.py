"""Creative gallery list API."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.db.models import Base
from benchbase.db.session import get_db
from benchbase.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("BENCHBASE_DB_URL", url)
    monkeypatch.setenv("BENCHBASE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BENCHBASE_CREATIVE_ARENA", "1")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.anyio
async def test_list_attempts_after_start(client):
    start = await client.post(
        "/api/creative/attempts/start",
        json={"model_name": "gallery-seat", "harness": "mock"},
    )
    assert start.status_code == 200
    uuid = start.json()["attempt_uuid"]
    listed = await client.get("/api/creative/attempts?limit=5")
    assert listed.status_code == 200
    rows = listed.json()
    assert any(r["attempt_uuid"] == uuid for r in rows)
    assert rows[0]["model_name"] == "gallery-seat"