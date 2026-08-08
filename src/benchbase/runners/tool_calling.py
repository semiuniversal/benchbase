"""Tool-calling (BFCL-style) runner with AST-ish argument match."""

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


def _parse_tool_call(text: str) -> tuple[str | None, dict | None]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        obj = json.loads(raw)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None, None
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return None, None
    if not isinstance(obj, dict):
        return None, None
    name = obj.get("name") or (obj.get("function") or {}).get("name")
    args = obj.get("arguments") or obj.get("args") or (obj.get("function") or {}).get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = None
    return (str(name) if name else None), (args if isinstance(args, dict) else None)


def _args_match(got: dict | None, expect: dict | None) -> bool:
    if expect is None:
        return got is None
    if got is None:
        return False
    # Order-insensitive; coerce numbers loosely.
    if set(got) != set(expect):
        return False
    for k, v in expect.items():
        gv = got.get(k)
        if gv == v:
            continue
        try:
            if float(gv) == float(v):
                continue
        except Exception:
            pass
        if str(gv) != str(v):
            return False
    return True


@register_runner("tool_calling")
class ToolCallingRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model)])
        model: Model = run_db.model
        client = LiteLLMClient(base_url=model.endpoint_url)
        items = select_tier_items(
            load_fixture_items("tool_calling"),
            run_tier(run),
            {"smoke": 5, "standard": 125, "thorough": 125},
        )
        rows: list[dict[str, Any]] = []
        mode = "prompting"
        for item in items:
            prompt = item["prompt"]
            if item.get("expected_name"):
                prompt += (
                    "\nRespond with ONLY JSON: "
                    '{"name":"...","arguments":{...}}'
                )
            text, latency = await chat_once(
                client,
                model.name,
                [{"role": "user", "content": prompt}],
                max_tokens=256,
            )
            name, args = _parse_tool_call(text)
            expect_name = item.get("expected_name")
            if expect_name is None:
                # Irrelevance: pass if no tool call parsed.
                passed = name is None
            else:
                passed = name == expect_name and _args_match(args, item.get("expected_args"))
            rows.append(
                {
                    "item_id": item["item_id"],
                    "passed": passed,
                    "raw_answer": text[:1000],
                    "latency_ms": latency,
                    "detail": {"category": item.get("category"), "mode": mode},
                }
            )
        await persist_axis_result(
            db, run, "tool_calling:bfcl", rows, metrics={"tool_call_mode": mode}
        )
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "tool_calling", "axis": "tool_calling"}
