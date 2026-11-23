"""WP6 adapter registry."""

from __future__ import annotations

import pytest

from benchbase.adapters.registry import adapter_descriptors, get_adapter
from benchbase.config import Settings


@pytest.mark.asyncio
async def test_tinybenchmarks_offline_run():
    adapter = get_adapter("tinybenchmarks")
    assert adapter is not None
    out = await adapter.run({"suite": "tiny_mmlu"})
    assert out["status"] == "ok"
    assert out["expected_score"] == 0.62


def test_adapters_hidden_without_flag():
    settings = Settings(upstream_adapters_enabled=False)
    assert adapter_descriptors(settings) == []


def test_adapters_visible_when_enabled():
    settings = Settings(upstream_adapters_enabled=True)
    ids = {row["protocol_id"] for row in adapter_descriptors(settings)}
    assert "tinybenchmarks" in ids