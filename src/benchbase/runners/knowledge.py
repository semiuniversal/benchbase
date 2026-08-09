"""Multiple-choice quality runners (knowledge / reasoning)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.controls import is_control_model_name
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
    suite_version_for_run,
)
from benchbase.runners.progress_log import AxisProgressLog
from benchbase.runners.registry import register_runner


async def _run_mc_axis(
    run: Run,
    db: AsyncSession,
    *,
    axis: str,
    task_name: str,
    tier_n: dict[str, int],
) -> None:
    run_db = await db.get(Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)])
    model: Model = run_db.model
    client = None if is_control_model_name(model.name) else LiteLLMClient(base_url=model.endpoint_url)
    version = suite_version_for_run(run_db)
    items = select_tier_items(load_fixture_items(axis, version), run_tier(run), tier_n)
    progress = AxisProgressLog(
        title=run_db.suite.name if run_db.suite else axis,
        total=len(items),
        tier=run_tier(run).value,
    )
    rows: list[dict[str, Any]] = []
    for item in items:
        try:
            text, latency = await chat_once(
                client,
                model.name,
                [{"role": "user", "content": item["prompt"]}],
                max_tokens=64,
            )
            letter, reason = extract_mc_letter(text)
            passed = bool(letter and letter == item.get("answer"))
            row = {
                "item_id": item["item_id"],
                "passed": passed,
                "raw_answer": (letter or text)[:500],
                "latency_ms": latency,
                "reason": None if passed else (reason or "incorrect"),
                "extracted": letter,
            }
        except Exception as exc:
            row = {
                "item_id": item["item_id"],
                "passed": None,
                "raw_answer": str(exc)[:500],
                "scorer_error": True,
                "reason": "scorer-error",
            }
        rows.append(row)
        progress.record(row, sample_text=str(item.get("prompt", ""))[:80])
    result = await persist_axis_result(db, run, task_name, rows)
    progress.finish(result.score)
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
