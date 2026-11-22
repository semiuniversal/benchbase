"""Single-axis launch and full rerun."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.db.models import Base, BenchmarkAxis, BenchmarkSuite, Model, ModelStatus, RunStatus
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
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        session.add(
            Model(
                name="axis-seat",
                endpoint_url="http://127.0.0.1:9",
                color="blue",
                status=ModelStatus.ACTIVE,
            )
        )
        session.add(
            BenchmarkSuite(
                name="Smoke",
                axis=BenchmarkAxis.SMOKE,
                category=BenchmarkAxis.SMOKE,
                runner_class="smoke",
                suite_version="v2",
            )
        )
        await session.commit()

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
async def test_axis_start_requires_active_model(client, monkeypatch):
    from benchbase.litellm_probe import probe_sticky_min_tokens

    async def fake_probe(*_a, **_k):
        return {"ok": True, "sticky_min_tokens": False}

    monkeypatch.setattr(
        "benchbase.litellm_probe.probe_sticky_min_tokens",
        fake_probe,
    )
    suites = await client.get("/api/benchmarks/suites")
    suite_id = suites.json()[0]["id"]
    models = await client.get("/api/models/")
    assert models.status_code == 200, models.text
    model_id = models.json()[0]["id"]
    r = await client.post(
        "/api/benchmarks/axis/start",
        json={"model_id": model_id, "suite_id": suite_id, "tier": "smoke"},
    )
    assert r.status_code == 200
    assert r.json().get("status") in ("running", "idle")