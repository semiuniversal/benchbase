"""Instruction-following (IFEval-style) rule verification."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Model, Run
from benchbase.litellm_client import LiteLLMClient
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.quality_common import (
    chat_once,
    load_fixture_items,
    persist_axis_result,
    run_tier,
    select_tier_items,
)
from benchbase.runners.registry import register_runner


def _check_rule(text: str, rule: dict[str, Any]) -> bool:
    if not rule:
        return False
    if rule.get("type") == "word_count":
        words = [w for w in text.strip().split() if w]
        return len(words) == int(rule.get("n", -1))
    return False


@register_runner("instruction")
class InstructionRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model)])
        model: Model = run_db.model
        client = LiteLLMClient(base_url=model.endpoint_url)
        items = select_tier_items(
            load_fixture_items("instruction"),
            run_tier(run),
            {"smoke": 5, "standard": 50, "thorough": 50},
        )
        rows: list[dict[str, Any]] = []
        for item in items:
            text, latency = await chat_once(
                client,
                model.name,
                [{"role": "user", "content": item["prompt"]}],
                max_tokens=128,
            )
            rows.append(
                {
                    "item_id": item["item_id"],
                    "passed": _check_rule(text, item.get("rule") or {}),
                    "raw_answer": text[:1000],
                    "latency_ms": latency,
                }
            )
        await persist_axis_result(db, run, "instruction:ifeval", rows)
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "instruction", "axis": "instruction"}
