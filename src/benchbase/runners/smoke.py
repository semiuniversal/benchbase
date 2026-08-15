"""Smoke coherency / format-check runner."""

from __future__ import annotations

import json
import re
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
    run_quality_items,
    run_tier,
    select_tier_items,
    suite_version_for_run,
)
from benchbase.runners.registry import register_runner


def _check_code(text: str) -> bool:
    return bool(re.search(r"```(?:python)?\s*\n[\s\S]+?```", text))


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
        return isinstance(obj, dict) and "name" in obj and "arguments" in obj
    except Exception:
        return False


def _check_coherency(text: str, prompt: str) -> bool:
    if not text or len(text.strip()) < 3:
        return False
    if text.strip().lower().startswith("error"):
        return False
    if text.strip() == prompt.strip() or prompt.strip() in text:
        return False
    if "FORBIDDEN_WORD_xyzzy" in text or "THIS_IS_WRONG" in text:
        return False
    return True


@register_runner("smoke")
class SmokeRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> str:
        run_db = await db.get(
            Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)]
        )
        model: Model = run_db.model
        client = None if is_control_model_name(model.name) else LiteLLMClient(base_url=model.endpoint_url)
        version = suite_version_for_run(run_db)
        items = select_tier_items(
            load_fixture_items("smoke", version),
            run_tier(run),
            {"smoke": 25, "standard": 25, "thorough": 25},
        )

        async def score_one(item: dict[str, Any]) -> dict[str, Any]:
            text, latency = await chat_once(
                client, model.name, [{"role": "user", "content": item["prompt"]}], max_tokens=256
            )
            check = item.get("check")
            reason = "incorrect"
            if check == "coherency":
                ok = _check_coherency(text, item["prompt"])
                if not text.strip():
                    reason = "unparseable"
            elif check == "code_extract":
                ok = _check_code(text)
                if not ok and not text.strip():
                    reason = "unparseable"
            elif check == "json_parse":
                ok = _check_json(text)
                if not ok:
                    reason = "unparseable" if not text.strip() else "incorrect"
            elif check == "tool_call_syntax":
                ok = _check_tool(text)
                if not ok:
                    reason = "unparseable" if not text.strip() else "incorrect"
            elif check == "mc_letter":
                letter, extract_reason = extract_mc_letter(text)
                ok = letter == item.get("answer")
                reason = None if ok else (extract_reason or "incorrect")
            else:
                ok = False
                reason = "scorer-error"
            return {
                "item_id": item["item_id"],
                "passed": ok,
                "raw_answer": text[:2000],
                "latency_ms": latency,
                "reason": None if ok else reason,
                "detail": {"check": check},
                "scorer_error": reason == "scorer-error",
            }

        outcome, _ = await run_quality_items(
            db,
            run,
            "smoke:format",
            items,
            score_one,
            metrics={"tier": run.tier.value},
            title=run_db.suite.name if run_db.suite else "smoke",
            sample_text_fn=lambda item, _row: str(item.get("prompt", ""))[:80],
        )
        return outcome

    def metadata(self) -> dict[str, Any]:
        return {"name": "smoke", "axis": "smoke", "description": "Format / coherency probes"}
