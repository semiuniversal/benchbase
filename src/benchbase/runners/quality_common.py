"""Shared helpers for v2 quality-axis runners."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Result, ResultItem, Run, RunTier
from benchbase.litellm_client import LiteLLMClient
from benchbase.stats import proportion_score, wilson_interval

FIXTURES_ROOT = (
    Path(__file__).resolve().parent.parent.parent.parent / "corpus" / "suites"
)

_TIER_KEY = {
    RunTier.SMOKE: "smoke",
    RunTier.STANDARD: "standard",
    RunTier.THOROUGH: "thorough",
}


def load_fixture_items(axis: str, version: str = "v1") -> list[dict[str, Any]]:
    path = FIXTURES_ROOT / axis / version / "items.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("items") or [])
    return list(data)


def select_tier_items(
    items: list[dict[str, Any]],
    tier: RunTier,
    tier_n: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    key = _TIER_KEY.get(tier, "standard")
    n = (tier_n or {}).get(key)
    if n is None:
        defaults = {"smoke": 5, "standard": 100, "thorough": 300}
        n = defaults.get(key, 100)
    # Fixed prefix of the versioned list — never shuffle.
    return items[: max(0, min(n, len(items)))]


def extract_mc_letter(text: str) -> str | None:
    if not text:
        return None
    # Prefer trailing "Answer: X" patterns.
    m = re.search(r"(?:answer|final)\s*[:\-]?\s*([A-D])\b", text, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b([A-D])\b\s*$", text.strip(), re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b([A-D])\b", text)
    return m.group(1).upper() if m else None


def extract_final_number(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"(?:answer|final)\s*[:\-]?\s*(-?\d+(?:\.\d+)?)", text, re.I)
    if m:
        return m.group(1)
    nums = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return nums[-1] if nums else None


async def chat_once(
    client: LiteLLMClient,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> tuple[str, float]:
    t0 = time.perf_counter()
    resp = await client.chat(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    latency = (time.perf_counter() - t0) * 1000.0
    choices = resp.get("choices") or []
    content = ""
    if choices:
        msg = choices[0].get("message") or {}
        content = msg.get("content") or msg.get("reasoning_content") or ""
    return str(content), latency


async def persist_axis_result(
    db: AsyncSession,
    run: Run,
    task_name: str,
    item_rows: list[dict[str, Any]],
    *,
    primary_method: str = "raw",
    metrics: dict[str, Any] | None = None,
) -> Result:
    """Persist aggregate + per-item rows. item_rows need item_id, passed, raw_answer?, latency_ms?."""
    n = len(item_rows)
    successes = sum(1 for r in item_rows if r.get("passed"))
    score = proportion_score(successes, n)
    ci_low, ci_high = wilson_interval(successes, n)
    result = Result(
        run_id=run.id,
        task_name=task_name,
        score=score,
        ci_low=ci_low,
        ci_high=ci_high,
        n_items=n,
        primary_method=primary_method,
        metrics_json=json.dumps(
            {
                "successes": successes,
                "n": n,
                **(metrics or {}),
            }
        ),
    )
    db.add(result)
    await db.flush()
    for row in item_rows:
        db.add(
            ResultItem(
                result_id=result.id,
                item_id=str(row["item_id"]),
                passed=bool(row.get("passed")) if row.get("passed") is not None else None,
                raw_answer=row.get("raw_answer"),
                latency_ms=row.get("latency_ms"),
                detail_json=json.dumps(row.get("detail")) if row.get("detail") is not None else None,
            )
        )
    await db.flush()
    return result


def run_tier(run: Run) -> RunTier:
    return run.tier if isinstance(run.tier, RunTier) else RunTier.STANDARD
