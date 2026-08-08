"""Math (tinyGSM8K-style) runner with final-number extraction."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Model, Run
from benchbase.litellm_client import LiteLLMClient
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.quality_common import (
    chat_once,
    extract_final_number,
    load_fixture_items,
    persist_axis_result,
    run_tier,
    select_tier_items,
)
from benchbase.runners.registry import register_runner


@register_runner("math")
class MathRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model)])
        model: Model = run_db.model
        client = LiteLLMClient(base_url=model.endpoint_url)
        items = select_tier_items(
            load_fixture_items("math"),
            run_tier(run),
            {"smoke": 5, "standard": 100, "thorough": 100},
        )
        rows: list[dict[str, Any]] = []
        for item in items:
            text, latency = await chat_once(
                client,
                model.name,
                [{"role": "user", "content": item["prompt"]}],
                max_tokens=256,
            )
            got = extract_final_number(text)
            expect = str(item.get("answer"))
            rows.append(
                {
                    "item_id": item["item_id"],
                    "passed": got == expect,
                    "raw_answer": got or text[:500],
                    "latency_ms": latency,
                }
            )
        await persist_axis_result(db, run, "math:tiny_gsm8k", rows)
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "math", "axis": "math"}
