"""Multiple-choice quality runners (knowledge / reasoning)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Model, Run
from benchbase.litellm_client import LiteLLMClient
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.quality_common import (
    chat_once,
    extract_mc_letter,
    load_fixture_items,
    persist_axis_result,
    run_tier,
    select_tier_items,
)
from benchbase.runners.registry import register_runner


async def _run_mc_axis(
    run: Run,
    db: AsyncSession,
    *,
    axis: str,
    task_name: str,
    tier_n: dict[str, int],
) -> None:
    run_db = await db.get(Run, run.id, options=[selectinload(Run.model)])
    model: Model = run_db.model
    client = LiteLLMClient(base_url=model.endpoint_url)
    items = select_tier_items(load_fixture_items(axis), run_tier(run), tier_n)
    rows: list[dict[str, Any]] = []
    for item in items:
        text, latency = await chat_once(
            client,
            model.name,
            [{"role": "user", "content": item["prompt"]}],
            max_tokens=64,
        )
        letter = extract_mc_letter(text)
        rows.append(
            {
                "item_id": item["item_id"],
                "passed": letter == item.get("answer"),
                "raw_answer": letter or text[:500],
                "latency_ms": latency,
            }
        )
    await persist_axis_result(db, run, task_name, rows)
    await db.commit()


@register_runner("knowledge")
class KnowledgeRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        await _run_mc_axis(
            run,
            db,
            axis="knowledge",
            task_name="knowledge:tiny_mmlu",
            tier_n={"smoke": 5, "standard": 100, "thorough": 100},
        )

    def metadata(self) -> dict[str, Any]:
        return {"name": "knowledge", "axis": "knowledge"}


@register_runner("reasoning")
class ReasoningRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        await _run_mc_axis(
            run,
            db,
            axis="reasoning",
            task_name="reasoning:tiny_arc",
            tier_n={"smoke": 5, "standard": 100, "thorough": 100},
        )

    def metadata(self) -> dict[str, Any]:
        return {"name": "reasoning", "axis": "reasoning"}
