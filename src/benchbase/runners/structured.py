"""Structured JSON output validation against schemas."""

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
    load_fixture_items,
    run_quality_items,
    run_tier,
    select_tier_items,
    suite_version_for_run,
)
from benchbase.runners.registry import register_runner


def _strip_fences(text: str) -> str:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _validate(instance: Any, schema: dict[str, Any]) -> bool:
    """JSON Schema subset: object/array/string/integer/number/boolean/enum. Unknown → fail."""
    if not schema:
        return False
    if "enum" in schema:
        return instance in schema["enum"]
    t = schema.get("type")
    if t is None:
        return False
    if t == "object":
        if not isinstance(instance, dict):
            return False
        for req in schema.get("required") or []:
            if req not in instance:
                return False
        props = schema.get("properties") or {}
        for key, sub in props.items():
            if key in instance and not _validate(instance[key], sub):
                return False
        return True
    if t == "array":
        if not isinstance(instance, list):
            return False
        item_schema = schema.get("items")
        if not item_schema:
            return False
        return all(_validate(x, item_schema) for x in instance)
    if t == "string":
        return isinstance(instance, str)
    if t == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if t == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool)
    if t == "boolean":
        return isinstance(instance, bool)
    return False


@register_runner("structured")
class StructuredRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> str:
        run_db = await db.get(
            Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)]
        )
        model: Model = run_db.model
        client = None if is_control_model_name(model.name) else LiteLLMClient(base_url=model.endpoint_url)
        version = suite_version_for_run(run_db)
        items = select_tier_items(
            load_fixture_items("structured", version),
            run_tier(run),
            {"smoke": 5, "standard": 30, "thorough": 30},
        )
        strict = run.tier.value == "thorough"

        async def score_one(item: dict[str, Any]) -> dict[str, Any]:
            text, latency = await chat_once(
                client,
                model.name,
                [{"role": "user", "content": item["prompt"]}],
                max_tokens=256,
            )
            reason = "incorrect"
            passed = False
            try:
                raw = text.strip() if strict else _strip_fences(text)
                if not raw:
                    reason = "unparseable"
                else:
                    obj = json.loads(raw)
                    schema = item.get("schema") or {}
                    if schema.get("oneOf_hint") and isinstance(obj, dict):
                        kind = obj.get("kind")
                        val = obj.get("value")
                        if kind == "text" and isinstance(val, str):
                            passed = _validate(
                                {**obj, "value": val},
                                {
                                    **schema,
                                    "properties": {
                                        **schema.get("properties", {}),
                                        "value": {"type": "string"},
                                    },
                                },
                            )
                        elif kind == "number" and isinstance(val, (int, float)):
                            passed = True
                        else:
                            passed = False
                    else:
                        passed = _validate(obj, schema)
                    reason = None if passed else "incorrect"
            except json.JSONDecodeError:
                reason = "unparseable"
                passed = False
            return {
                "item_id": item["item_id"],
                "passed": passed,
                "raw_answer": text[:1000],
                "latency_ms": latency,
                "reason": reason,
                "detail": {"strict": strict},
            }

        outcome, _ = await run_quality_items(
            db,
            run,
            "structured:json_schema",
            items,
            score_one,
            title=run_db.suite.name if run_db.suite else "structured",
            sample_text_fn=lambda item, _row: str(item.get("prompt", ""))[:80],
        )
        return outcome

    def metadata(self) -> dict[str, Any]:
        return {"name": "structured", "axis": "structured"}
