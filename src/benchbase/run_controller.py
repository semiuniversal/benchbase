"""Track and cancel/pause in-flight benchmark runs."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asyncio.subprocess import Process

logger = logging.getLogger(__name__)

_cancelled: set[int] = set()
_pause_requested: set[int] = set()
_tasks: dict[int, asyncio.Task] = {}
_procs: dict[int, Process] = {}


def register_task(run_id: int, task: asyncio.Task) -> None:
    _tasks[run_id] = task


def unregister_task(run_id: int) -> None:
    _tasks.pop(run_id, None)


def register_subprocess(run_id: int, proc: Process) -> None:
    _procs[run_id] = proc


def unregister_subprocess(run_id: int) -> None:
    _procs.pop(run_id, None)


def is_cancelled(run_id: int) -> bool:
    return run_id in _cancelled


def clear_cancelled(run_id: int) -> None:
    _cancelled.discard(run_id)


def request_pause(run_id: int) -> None:
    """Ask a quality runner to stop cooperatively between items."""
    _pause_requested.add(run_id)
    logger.info("Pause requested for run #%d", run_id)


def is_pause_requested(run_id: int) -> bool:
    return run_id in _pause_requested


def clear_pause(run_id: int) -> None:
    _pause_requested.discard(run_id)


def reset_run_tracking(run_id: int) -> None:
    """Drop in-memory cancel/pause/task/subprocess state for a run."""
    from benchbase.run_timing import RunTimingTracker

    clear_cancelled(run_id)
    clear_pause(run_id)
    _tasks.pop(run_id, None)
    _procs.pop(run_id, None)
    RunTimingTracker.clear(run_id)


def reset_all_run_tracking() -> None:
    """Clear all in-memory run tracking (server startup)."""
    from benchbase.run_timing import RunTimingTracker

    _cancelled.clear()
    _pause_requested.clear()
    _tasks.clear()
    _procs.clear()
    RunTimingTracker.clear_all()


def kill_subprocess(proc: Process) -> None:
    """Terminate a subprocess and any child processes (lm-eval/litebench workers)."""
    if proc.returncode is not None:
        return
    pid = proc.pid
    if pid is None:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        logger.info("Killed process group pgid=%d (pid=%d)", os.getpgid(pid), pid)
    except (ProcessLookupError, OSError, PermissionError):
        try:
            proc.kill()
            logger.info("Killed subprocess pid=%d", pid)
        except ProcessLookupError:
            pass


async def cancel_run(run_id: int) -> bool:
    """Stop a running benchmark: kill subprocess tree and cancel the run task."""
    proc = _procs.get(run_id)
    task = _tasks.get(run_id)
    has_proc = proc is not None and proc.returncode is None
    has_task = task is not None and not task.done()

    if not has_proc and not has_task:
        return False

    _cancelled.add(run_id)
    # Cancel supersedes pause.
    _pause_requested.discard(run_id)

    if has_proc:
        logger.info("Killing subprocess for run #%d", run_id)
        kill_subprocess(proc)

    if has_task:
        task.cancel()

    return True


async def pause_run(run_id: int) -> bool:
    """Request cooperative pause. Does not cancel the asyncio task."""
    task = _tasks.get(run_id)
    if task is None or task.done():
        return False
    request_pause(run_id)
    return True
