"""Abstract base class for benchmark runners."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Run


class BenchmarkRunner(ABC):
    """All benchmark runners implement this interface."""

    @abstractmethod
    async def run(self, run: Run, db: AsyncSession) -> None:
        """Execute the benchmark and persist results to the database."""

    @abstractmethod
    def metadata(self) -> dict[str, Any]:
        """Return runner metadata (name, category, description, etc.)."""
