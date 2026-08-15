"""SQLite busy-retry helpers used under parallel model concurrency."""

from __future__ import annotations

import asyncio

from sqlalchemy.exc import OperationalError

from benchbase.db.session import _is_sqlite_busy_error, commit_with_busy_retry


def test_is_sqlite_busy_error_detects_locked():
    assert _is_sqlite_busy_error(OperationalError("stmt", {}, Exception("database is locked")))
    assert _is_sqlite_busy_error(Exception("PendingRollbackError: database is locked"))
    assert not _is_sqlite_busy_error(ValueError("nope"))


def test_commit_with_busy_retry_succeeds_after_transient_lock():
    class FakeSession:
        def __init__(self) -> None:
            self.calls = 0
            self.rollbacks = 0

        async def commit(self) -> None:
            self.calls += 1
            if self.calls < 3:
                raise OperationalError("COMMIT", {}, Exception("database is locked"))

        async def rollback(self) -> None:
            self.rollbacks += 1

    session = FakeSession()
    asyncio.run(commit_with_busy_retry(session, attempts=5, base_delay_s=0.001))  # type: ignore[arg-type]
    assert session.calls == 3
    assert session.rollbacks == 2
