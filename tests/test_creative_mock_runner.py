"""Mock creative event stream."""

import asyncio

import pytest

from benchbase.creative.events import replay
from benchbase.creative.mock_runner import run_mock_attempt
from benchbase.creative.workspace import provision_attempt_workspace


@pytest.mark.asyncio
async def test_mock_runner_emits_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("BENCHBASE_DATA_DIR", str(tmp_path))
    from benchbase import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    root = provision_attempt_workspace("u1", model_name="m1")
    await run_mock_attempt(root, "u1", model_name="m1", delay_s=0.01)
    events = replay(root)
    kinds = [e["kind"] for e in events]
    assert "tool_start" in kinds and "complete" in kinds
    assert (root / "project" / "index.html").is_file()