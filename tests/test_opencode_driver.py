"""WP7 OpenCode driver mock path."""

from __future__ import annotations

import pytest

from benchbase.creative.opencode_driver import run_attempt


@pytest.mark.asyncio
async def test_opencode_driver_mock_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BENCHBASE_OPENCODE_LIVE", raising=False)
    out = await run_attempt(
        workspace=str(tmp_path / "ws"),
        prompt="build app",
        endpoint_url="http://127.0.0.1/v1",
    )
    assert out["harness"] == "mock"
    assert out["runnable"] is True