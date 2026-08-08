"""Long-context NIAH-style retrieval runner."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Model, Run, RunTier
from benchbase.litellm_client import LiteLLMClient
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.quality_common import (
    chat_once,
    load_fixture_items,
    persist_axis_result,
    run_tier,
)
from benchbase.runners.registry import register_runner

_FILLER = (
    "It was a bright cold day in April, and the clocks were striking thirteen. "
    "Winston Smith slipped quickly through the glass doors of Victory Mansions. "
)


def _pad_to_approx_chars(needle: str, length_tokens: int) -> str:
    # Rough 4 chars/token estimate.
    target = max(500, length_tokens * 4)
    half = max(100, (target - len(needle)) // 2)
    left = (_FILLER * (half // len(_FILLER) + 1))[:half]
    right = (_FILLER * (half // len(_FILLER) + 1))[:half]
    return left + f"\n<<{needle}>>\n" + right


@register_runner("long_context")
class LongContextRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model)])
        model: Model = run_db.model
        client = LiteLLMClient(base_url=model.endpoint_url)
        tier = run_tier(run)
        allowed = {8000, 16000} if tier != RunTier.THOROUGH else {8000, 16000, 32000}
        if tier == RunTier.SMOKE:
            allowed = {8000}
        items = [
            it
            for it in load_fixture_items("long_context")
            if it.get("length") in allowed
        ]
        if tier == RunTier.SMOKE:
            items = items[:5]
        rows: list[dict[str, Any]] = []
        by_length: dict[int, list[bool]] = {}
        for item in items:
            needle = item["needle"]
            doc = _pad_to_approx_chars(needle, int(item["length"]))
            prompt = (
                f"{item.get('prompt_template')}\n\nDOCUMENT:\n{doc}\n\n"
                "What is the special code? Reply with only the code."
            )
            text, latency = await chat_once(
                client,
                model.name,
                [{"role": "user", "content": prompt}],
                max_tokens=64,
            )
            passed = needle in text
            by_length.setdefault(int(item["length"]), []).append(passed)
            rows.append(
                {
                    "item_id": item["item_id"],
                    "passed": passed,
                    "raw_answer": text[:200],
                    "latency_ms": latency,
                    "detail": {"length": item["length"]},
                }
            )
        breakdown = {
            str(k): round(100.0 * sum(v) / len(v), 1) if v else None
            for k, v in by_length.items()
        }
        await persist_axis_result(
            db, run, "long_context:niah", rows, metrics={"per_length": breakdown}
        )
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "long_context", "axis": "long_context"}
