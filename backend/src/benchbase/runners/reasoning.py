"""Reasoning benchmark runner stub (GSM8K / MMLU-style)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner


@register_runner("reasoning")
class ReasoningRunner(BenchmarkRunner):
    """Placeholder for GSM8K / MMLU-style reasoning benchmarks."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        raise NotImplementedError(
            "Reasoning benchmark runner is not yet implemented. "
            "This will integrate GSM8K, MMLU, or similar evaluation suites."
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Reasoning Benchmark",
            "category": "reasoning",
            "description": "GSM8K, MMLU, and similar complex reasoning evaluation suites.",
        }
