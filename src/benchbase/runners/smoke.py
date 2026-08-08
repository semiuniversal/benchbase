"""Smoke coherency / format-check runner."""

from __future__ import annotations

import json
import re
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


def _check_code(text: str) -> bool:
    return bool(re.search(r"```(?:python)?\s*\n[\s\S]+?```", text)) or "def " in text


def _check_json(text: str) -> bool:
    try:
        raw = text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        obj = json.loads(raw)
        return isinstance(obj, dict)
    except Exception:
        return False


def _check_tool(text: str) -> bool:
    try:
        raw = text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        obj = json.loads(raw)
        return isinstance(obj, dict) and "name" in obj
    except Exception:
        return False


def _check_coherency(text: str) -> bool:
    return bool(text) and len(text.strip()) >= 3 and not text.strip().lower().startswith("error")


@register_runner("smoke")
class SmokeRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model)])
        model: Model = run_db.model
        client = LiteLLMClient(base_url=model.endpoint_url)
        items = select_tier_items(load_fixture_items("smoke"), run_tier(run), {"smoke": 25, "standard": 25, "thorough": 25})
        rows: list[dict[str, Any]] = []
        for item in items:
            text, latency = await chat_once(
                client, model.name, [{"role": "user", "content": item["prompt"]}], max_tokens=256
            )
            check = item.get("check")
            if check == "coherency":
                ok = _check_coherency(text)
            elif check == "code_extract":
                ok = _check_code(text)
            elif check == "json_parse":
                ok = _check_json(text)
            elif check == "tool_call_syntax":
                ok = _check_tool(text)
            elif check == "mc_letter":
                letter = extract_mc_letter(text)
                ok = letter == item.get("answer")
            else:
                ok = False
            rows.append(
                {
                    "item_id": item["item_id"],
                    "passed": ok,
                    "raw_answer": text[:2000],
                    "latency_ms": latency,
                    "detail": {"check": check},
                }
            )
        # Smoke is pass/fail per check group in metrics; overall proportion for CI display.
        await persist_axis_result(db, run, "smoke:format", rows, metrics={"tier": run.tier.value})
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "smoke", "axis": "smoke", "description": "Format / coherency probes"}
