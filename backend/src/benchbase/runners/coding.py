"""Coding benchmark runner stub (HumanEval-style)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner


@register_runner("coding")
class CodingRunner(BenchmarkRunner):
    """Placeholder for HumanEval-style code generation benchmarks."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        raise NotImplementedError(
            "Coding benchmark runner is not yet implemented. "
            "This will integrate a HumanEval-style harness."
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Coding Benchmark",
            "category": "coding",
            "description": "HumanEval-style code generation and test-passing benchmarks.",
        }
