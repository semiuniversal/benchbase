"""Tool-use evaluation runner stub."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner


@register_runner("tool_use")
class ToolUseRunner(BenchmarkRunner):
    """Placeholder for instruction-following and tool-call evaluation."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        raise NotImplementedError(
            "Tool-use benchmark runner is not yet implemented. "
            "This will provide scenario-based evaluations for schema adherence "
            "and tool-call correctness."
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Tool Use Benchmark",
            "category": "tool_use",
            "description": "Scenario-based evaluations for instruction following and tool-call correctness.",
        }
