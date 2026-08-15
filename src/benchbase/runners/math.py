"""Math (tinyGSM8K) runner with final-number extraction."""

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
    extract_final_number,
    load_fixture_items,
    normalize_number,
    run_quality_items,
    run_tier,
    select_tier_items,
    suite_version_for_run,
)
from benchbase.runners.registry import register_runner


@register_runner("math")
class MathRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> str:
        run_db = await db.get(
            Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)]
        )
        model: Model = run_db.model
        client = None if is_control_model_name(model.name) else LiteLLMClient(base_url=model.endpoint_url)
        version = suite_version_for_run(run_db)
        items = select_tier_items(
            load_fixture_items("math", version),
            run_tier(run),
            {"smoke": 5, "standard": 100, "thorough": 100},
        )

        async def score_one(item: dict[str, Any]) -> dict[str, Any]:
            text, latency = await chat_once(
                client,
                model.name,
                [{"role": "user", "content": item["prompt"]}],
                max_tokens=512,
            )
            got, reason = extract_final_number(text)
            expect = normalize_number(str(item.get("answer")))
            passed = bool(got and normalize_number(got) == expect)
            return {
                "item_id": item["item_id"],
                "passed": passed,
                "raw_answer": (got or text)[:500],
                "latency_ms": latency,
                "reason": None if passed else (reason or "incorrect"),
                "extracted": got,
            }

        outcome, _ = await run_quality_items(
            db,
            run,
            "math:tiny_gsm8k",
            items,
            score_one,
            title=run_db.suite.name if run_db.suite else "math",
            sample_text_fn=lambda item, _row: str(item.get("prompt", ""))[:80],
        )
        return outcome

    def metadata(self) -> dict[str, Any]:
        return {"name": "math", "axis": "math"}
