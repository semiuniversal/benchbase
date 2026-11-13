"""Idle sticky-token watcher stores probe results and skips live benchmarks."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from benchbase.litellm_watch import _maybe_probe, note_probe, sticky_status


def test_note_probe_records_sticky_for_the_ui():
    note_probe(
        {
            "ok": False,
            "sticky_min_tokens": True,
            "detail": "min_tokens must be <= max_tokens=1",
            "model": "seat-a",
        }
    )
    status = sticky_status()
    assert status["sticky_min_tokens"] is True
    assert status["model"] == "seat-a"
    assert status["checked_at"]


def test_maybe_probe_skips_while_a_benchmark_is_active():
    with (
        patch("benchbase.batch_scheduler.benchmark_active", return_value=True),
        patch(
            "benchbase.litellm_probe.probe_litellm_quality_route",
            new_callable=AsyncMock,
        ) as probe,
    ):
        asyncio.run(_maybe_probe())
    probe.assert_not_awaited()


def test_maybe_probe_records_a_clean_route_when_idle():
    clean = {
        "ok": True,
        "sticky_min_tokens": False,
        "detail": "quality route accepts max_tokens=1 (no sticky min_tokens)",
        "model": "seat-a",
    }
    with (
        patch("benchbase.batch_scheduler.benchmark_active", return_value=False),
        patch(
            "benchbase.litellm_probe.probe_litellm_quality_route",
            new_callable=AsyncMock,
            return_value=clean,
        ),
    ):
        asyncio.run(_maybe_probe())
    status = sticky_status()
    assert status["sticky_min_tokens"] is False
    assert status["ok"] is True
