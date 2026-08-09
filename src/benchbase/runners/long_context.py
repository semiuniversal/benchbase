"""Long-context NIAH-style retrieval runner (exact-match)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.controls import is_control_model_name
from benchbase.db.models import Model, Run, RunTier
from benchbase.litellm_client import LiteLLMClient
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.quality_common import (
    chat_once,
    load_fixture_items,
    persist_axis_result,
    run_tier,
    suite_version_for_run,
)
from benchbase.runners.progress_log import AxisProgressLog
from benchbase.runners.registry import register_runner

_FILLER = (
    "It was a bright cold day in April, and the clocks were striking thirteen. "
    "Winston Smith slipped quickly through the glass doors of Victory Mansions. "
)


def _pad_to_approx_chars(needle: str, length_tokens: int) -> str:
    target = max(500, length_tokens * 4)
    half = max(100, (target - len(needle)) // 2)
    left = (_FILLER * (half // len(_FILLER) + 1))[:half]
    right = (_FILLER * (half // len(_FILLER) + 1))[:half]
    return left + f"\n<<{needle}>>\n" + right


def _extract_needle_answer(text: str, needle: str) -> tuple[bool, str | None]:
    if not text or not text.strip():
        return False, "unparseable"
    cleaned = text.strip().strip("`\"'")
    # Reject prompt-echo / document dump.
    if "DOCUMENT:" in cleaned or cleaned.count(_FILLER[:40]) > 0 or len(cleaned) > 500:
        if cleaned != needle and needle not in cleaned.split():
            return False, "incorrect"
    if cleaned == needle:
        return True, None
    lines = [ln.strip().strip("`\"'") for ln in cleaned.splitlines() if ln.strip()]
    if lines and lines[-1] == needle:
        return True, None
    # Short answers that clearly commit the needle (e.g. "The code is NEEDLE-…").
    if len(cleaned) <= len(needle) + 80 and re.search(
        rf"(?i)(?:^|[^A-Za-z0-9_-]){re.escape(needle)}(?:[^A-Za-z0-9_-]|$)", cleaned
    ):
        return True, None
    return False, "incorrect"


@register_runner("long_context")
class LongContextRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)])
        model: Model = run_db.model
        client = None if is_control_model_name(model.name) else LiteLLMClient(base_url=model.endpoint_url)
        tier = run_tier(run)
        version = suite_version_for_run(run_db)
        allowed = {8000, 16000} if tier != RunTier.THOROUGH else {8000, 16000, 32000}
        if tier == RunTier.SMOKE:
            allowed = {8000}
        items = [
            it
            for it in load_fixture_items("long_context", version)
            if it.get("length") in allowed
        ]
        if tier == RunTier.SMOKE:
            items = items[:5]
        progress = AxisProgressLog(
            title=run_db.suite.name if run_db.suite else "long_context",
            total=len(items),
            tier=tier.value,
        )
        rows: list[dict[str, Any]] = []
        by_length: dict[int, list[bool]] = {}
        for item in items:
            try:
                needle = item["needle"]
                if is_control_model_name(model.name):
                    doc = f"short-doc\n<<{needle}>>\nend"
                else:
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
                passed, reason = _extract_needle_answer(text, needle)
                by_length.setdefault(int(item["length"]), []).append(passed)
                row = {
                    "item_id": item["item_id"],
                    "passed": passed,
                    "raw_answer": text[:200],
                    "latency_ms": latency,
                    "reason": reason,
                    "detail": {"length": item["length"]},
                }
            except Exception as exc:
                row = {
                    "item_id": item["item_id"],
                    "passed": None,
                    "raw_answer": str(exc)[:500],
                    "scorer_error": True,
                    "reason": "scorer-error",
                    "detail": {"length": item.get("length")},
                }
            rows.append(row)
            progress.record(row, sample_text=str(item.get("needle", ""))[:80])
        breakdown = {
            str(k): round(100.0 * sum(v) / len(v), 1) if v else None
            for k, v in by_length.items()
        }
        result = await persist_axis_result(
            db, run, "long_context:niah", rows, metrics={"per_length": breakdown}
        )
        progress.finish(result.score)
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "long_context", "axis": "long_context"}
