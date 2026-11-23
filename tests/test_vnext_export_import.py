"""WP9 export/import packages."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from benchbase.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_import_persist_inert(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "benchbase.api.routes.export_pkg.IMPORT_DIR",
        tmp_path,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pkg = {
            "schema_version": "benchbase.export.v1",
            "package_type": "evaluation_evidence",
            "content_hash": "abc",
            "scorecards": [],
        }
        r = await client.post(
            "/api/export/import",
            json={"package": pkg, "dry_run": False, "persist": True},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["inert"] is True
        assert body["status"] == "stored"
        assert list(tmp_path.glob("*.json"))