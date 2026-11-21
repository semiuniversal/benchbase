"""In-process creative attempt runners (until external worker)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sqlalchemy import select

from benchbase.creative.events import replay
from benchbase.creative.mock_runner import run_mock_attempt
from benchbase.db.models import CreativeAttempt
from benchbase.db.session import get_session_factory

logger = logging.getLogger(__name__)

_terminal: dict[str, asyncio.Event] = {}
_tasks: dict[str, asyncio.Task[None]] = {}


def terminal_event(attempt_uuid: str) -> asyncio.Event:
    if attempt_uuid not in _terminal:
        _terminal[attempt_uuid] = asyncio.Event()
    return _terminal[attempt_uuid]


def is_terminal(attempt_uuid: str) -> bool:
    ev = _terminal.get(attempt_uuid)
    return ev is not None and ev.is_set()


async def _finalize_status(attempt_uuid: str, status: str) -> None:
    factory = get_session_factory()
    async with factory() as db:
        row = (
            await db.execute(
                select(CreativeAttempt).where(CreativeAttempt.attempt_uuid == attempt_uuid)
            )
        ).scalar_one_or_none()
        if row:
            row.status = status
            await db.commit()


async def _mock_job(workspace: Path, attempt_uuid: str, model_name: str) -> None:
    await _finalize_status(attempt_uuid, "running")
    try:
        await run_mock_attempt(workspace, attempt_uuid, model_name=model_name)
        events = replay(workspace)
        last = events[-1]["kind"] if events else "complete"
        status = "failed" if last == "error" else "completed"
        await _finalize_status(attempt_uuid, status)
    except Exception:
        logger.exception("mock attempt %s failed", attempt_uuid)
        await _finalize_status(attempt_uuid, "failed")
    finally:
        terminal_event(attempt_uuid).set()
        _tasks.pop(attempt_uuid, None)


def schedule_mock_attempt(workspace: Path, attempt_uuid: str, model_name: str) -> None:
    task = asyncio.create_task(_mock_job(workspace, attempt_uuid, model_name))
    _tasks[attempt_uuid] = task