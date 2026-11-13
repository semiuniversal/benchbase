"""Idle watcher for sticky LiteLLM min_tokens / ignore_eos.

The manual Settings probe stays available. This publishes the same check
so the UI can open a restart dialog without a button press. Probes are
skipped while a benchmark is queued or running.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)

_INTERVAL_S = 90.0
_BOOT_DELAY_S = 12.0

_status: dict[str, Any] = {
    "sticky_min_tokens": False,
    "ok": None,
    "detail": None,
    "model": None,
    "checked_at": None,
}
_wake = asyncio.Event()
_task: asyncio.Task[None] | None = None


def sticky_status() -> dict[str, Any]:
    """Last probe, plus whether a benchmark currently owns the proxy."""
    from benchbase.batch_scheduler import benchmark_active

    return {**_status, "benchmark_active": benchmark_active()}


def note_probe(result: dict[str, Any]) -> None:
    """Store a probe result for the UI."""
    _status["sticky_min_tokens"] = bool(result.get("sticky_min_tokens"))
    _status["ok"] = result.get("ok")
    _status["detail"] = result.get("detail")
    _status["model"] = result.get("model")
    _status["checked_at"] = datetime.datetime.now(datetime.UTC).isoformat()


def request_sticky_check() -> None:
    """Ask the watcher to probe as soon as the queue is idle."""
    _wake.set()


async def _maybe_probe() -> None:
    from benchbase.batch_scheduler import benchmark_active
    from benchbase.litellm_probe import probe_litellm_quality_route

    if benchmark_active():
        return
    try:
        result = await probe_litellm_quality_route(timeout=20)
    except Exception:
        logger.exception("Sticky LiteLLM probe failed")
        return
    note_probe(result)
    if result.get("sticky_min_tokens"):
        logger.warning(
            "Sticky LiteLLM params on %s: %s",
            result.get("model"),
            result.get("detail"),
        )


async def _loop() -> None:
    await asyncio.sleep(_BOOT_DELAY_S)
    while True:
        await _maybe_probe()
        _wake.clear()
        try:
            await asyncio.wait_for(_wake.wait(), timeout=_INTERVAL_S)
        except TimeoutError:
            pass


def start_sticky_watch() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())


async def stop_sticky_watch() -> None:
    global _task
    task = _task
    _task = None
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
