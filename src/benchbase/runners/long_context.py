"""Long-context NIAH / multi-needle / variable-tracking runner (exact-match)."""

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


def _filler_block(n_chars: int) -> str:
    if n_chars <= 0:
        return ""
    return (_FILLER * (n_chars // len(_FILLER) + 1))[:n_chars]


def _bury(payload: str, length_tokens: int, position: str = "middle") -> str:
    """Bury payload in filler without unique delimiter markers."""
    target = max(500, length_tokens * 4)
    body = f"\n{payload}\n"
    remaining = max(0, target - len(body))
    pos = (position or "middle").lower()
    if pos == "start":
        return body + _filler_block(remaining)
    if pos == "end":
        return _filler_block(remaining) + body
    left = remaining // 2
    return _filler_block(left) + body + _filler_block(remaining - left)


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
    if len(cleaned) <= len(needle) + 80 and re.search(
        rf"(?i)(?:^|[^A-Za-z0-9_-]){re.escape(needle)}(?:[^A-Za-z0-9_-]|$)", cleaned
    ):
        return True, None
    return False, "incorrect"


def _build_document(item: dict[str, Any], *, control: bool) -> str:
    kind = item.get("kind") or "niah"
    length = int(item.get("length") or 8000)
    position = str(item.get("position") or "middle")
    if control:
        if kind == "multi_needle":
            needles = item.get("needles") or {}
            blob = " ".join(f"{k}={v}" for k, v in needles.items())
            return f"short-doc\n{blob}\nend"
        if kind == "variable_tracking":
            return f"short-doc\n{item.get('snippet', '')}\nend"
        return f"short-doc\n{item.get('needle', '')}\nend"

    if kind == "multi_needle":
        needles = item.get("needles") or {}
        parts = [f"The {lab} code is {code}." for lab, code in needles.items()]
        rng_shift = abs(hash(item.get("item_id", ""))) % 3
        ordered = parts[rng_shift:] + parts[:rng_shift]
        return _bury(" ".join(ordered), length, position)

    if kind == "variable_tracking":
        snippet = str(item.get("snippet") or "")
        return _bury(snippet, length, position)

    needle = str(item.get("needle") or "")
    return _bury(needle, length, position)


def _select_items(items: list[dict[str, Any]], tier: RunTier) -> list[dict[str, Any]]:
    if tier == RunTier.SMOKE:
        short = [it for it in items if int(it.get("length") or 0) == 8000]
        return short[:5]
    # Standard and Thorough: 8k + 16k + 32k (Thorough keeps the full set).
    allowed = {8000, 16000, 32000}
    selected = [it for it in items if int(it.get("length") or 0) in allowed]
    if tier == RunTier.STANDARD:
        return selected
    return selected


@register_runner("long_context")
class LongContextRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)])
        model: Model = run_db.model
        client = None if is_control_model_name(model.name) else LiteLLMClient(base_url=model.endpoint_url)
        tier = run_tier(run)
        version = suite_version_for_run(run_db)
        items = _select_items(load_fixture_items("long_context", version), tier)
        progress = AxisProgressLog(
            title=run_db.suite.name if run_db.suite else "long_context",
            total=len(items),
            tier=tier.value,
        )
        rows: list[dict[str, Any]] = []
        by_length: dict[int, list[bool]] = {}
        by_kind: dict[str, list[bool]] = {}
        for item in items:
            try:
                needle = str(item["needle"])
                doc = _build_document(item, control=is_control_model_name(model.name))
                prompt = (
                    f"{item.get('prompt_template')}\n\nDOCUMENT:\n{doc}\n\n"
                    "Reply with only the requested value."
                )
                text, latency = await chat_once(
                    client,
                    model.name,
                    [{"role": "user", "content": prompt}],
                    max_tokens=64,
                )
                passed, reason = _extract_needle_answer(text, needle)
                length = int(item.get("length") or 0)
                kind = str(item.get("kind") or "niah")
                by_length.setdefault(length, []).append(passed)
                by_kind.setdefault(kind, []).append(passed)
                row = {
                    "item_id": item["item_id"],
                    "passed": passed,
                    "raw_answer": text[:200],
                    "latency_ms": latency,
                    "reason": reason,
                    "detail": {
                        "length": length,
                        "kind": kind,
                        "position": item.get("position"),
                    },
                }
            except Exception as exc:
                row = {
                    "item_id": item["item_id"],
                    "passed": None,
                    "raw_answer": str(exc)[:500],
                    "scorer_error": True,
                    "reason": "scorer-error",
                    "detail": {"length": item.get("length"), "kind": item.get("kind")},
                }
            rows.append(row)
            progress.record(row, sample_text=str(item.get("needle", ""))[:80])
        breakdown = {
            str(k): round(100.0 * sum(v) / len(v), 1) if v else None
            for k, v in by_length.items()
        }
        kind_breakdown = {
            k: round(100.0 * sum(v) / len(v), 1) if v else None
            for k, v in by_kind.items()
        }
        result = await persist_axis_result(
            db,
            run,
            "long_context:niah",
            rows,
            metrics={"per_length": breakdown, "per_kind": kind_breakdown},
        )
        progress.finish(result.score)
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "long_context", "axis": "long_context"}
