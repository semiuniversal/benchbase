"""Structured JSON output validation against schemas."""

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
    load_fixture_items,
    persist_axis_result,
    run_tier,
    select_tier_items,
)
from benchbase.runners.registry import register_runner


def _strip_fences(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _validate(instance: Any, schema: dict[str, Any], *, strict: bool) -> bool:
    """Minimal JSON Schema subset validator (object/array/string/integer/required)."""
    t = schema.get("type")
    if t == "object":
        if not isinstance(instance, dict):
            return False
        for req in schema.get("required") or []:
            if req not in instance:
                return False
        props = schema.get("properties") or {}
        for key, sub in props.items():
            if key in instance and not _validate(instance[key], sub, strict=strict):
                return False
        return True
    if t == "array":
        if not isinstance(instance, list):
            return False
        item_schema = schema.get("items") or {}
        return all(_validate(x, item_schema, strict=strict) for x in instance)
    if t == "string":
        return isinstance(instance, str)
    if t == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if t == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    return True


@register_runner("structured")
class StructuredRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model)])
        model: Model = run_db.model
        client = LiteLLMClient(base_url=model.endpoint_url)
        items = select_tier_items(
            load_fixture_items("structured"),
            run_tier(run),
            {"smoke": 5, "standard": 30, "thorough": 30},
        )
        strict = run.tier.value == "thorough"
        rows: list[dict[str, Any]] = []
        for item in items:
            text, latency = await chat_once(
                client,
                model.name,
                [{"role": "user", "content": item["prompt"]}],
                max_tokens=256,
            )
            passed = False
            try:
                obj = json.loads(_strip_fences(text) if not strict else text.strip())
                passed = _validate(obj, item.get("schema") or {}, strict=strict)
            except Exception:
                passed = False
            rows.append(
                {
                    "item_id": item["item_id"],
                    "passed": passed,
                    "raw_answer": text[:1000],
                    "latency_ms": latency,
                    "detail": {"strict": strict},
                }
            )
        await persist_axis_result(db, run, "structured:json_schema", rows)
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "structured", "axis": "structured"}
