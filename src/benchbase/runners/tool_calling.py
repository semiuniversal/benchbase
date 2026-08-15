"""Tool-calling (BFCL) runner with AST-ish argument match."""

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
    is_infra_error,
    load_fixture_items,
    run_quality_items,
    run_tier,
    select_tier_items,
    suite_version_for_run,
)
from benchbase.runners.registry import register_runner


def _parse_tool_call(text: str) -> tuple[str | None, dict | None, str | None]:
    """Parse a committed tool call. Embedded JSON inside echoed prompts does not count."""
    if not text or not text.strip():
        return None, None, "unparseable"
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # Reject prompt-echo: must be compact JSON, not the instruction blob.
    if "You are a function-calling assistant" in raw or (
        "Tools:" in raw and "User:" in raw and len(raw) > 300
    ):
        return None, None, None
    obj: Any = None
    try:
        obj = json.loads(raw)
    except Exception:
        # Allow a single trailing JSON object only if the prefix is tiny.
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])\s*$", raw)
        if not m or m.start() > 40:
            return None, None, None
        try:
            obj = json.loads(m.group(1))
        except Exception:
            return None, None, "unparseable"
    if isinstance(obj, list) and obj:
        obj = obj[0]
    if not isinstance(obj, dict):
        return None, None, "unparseable"
    name = obj.get("name") or (obj.get("function") or {}).get("name")
    args = obj.get("arguments") or obj.get("args") or (obj.get("function") or {}).get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = None
    if not name:
        return None, None, "unparseable"
    return str(name), (args if isinstance(args, dict) else {}), None


def _args_match(got: dict | None, expect: dict | None) -> bool:
    if expect is None:
        return True  # name-only mode
    if got is None:
        return False
    for k, v in expect.items():
        if k not in got:
            return False
        gv = got.get(k)
        if gv == v:
            continue
        try:
            if float(gv) == float(v):
                continue
        except Exception:
            pass
        if str(gv).lower() != str(v).lower():
            return False
    return True


def _openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if not name:
            continue
        params = t.get("parameters") or {"type": "object", "properties": {}}
        # BFCL uses type: dict — normalize for OpenAI.
        if params.get("type") == "dict":
            params = {**params, "type": "object"}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": t.get("description") or "",
                    "parameters": params,
                },
            }
        )
    return out


@register_runner("tool_calling")
class ToolCallingRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> str:
        run_db = await db.get(
            Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)]
        )
        model: Model = run_db.model
        client = None if is_control_model_name(model.name) else LiteLLMClient(base_url=model.endpoint_url)
        version = suite_version_for_run(run_db)
        items = select_tier_items(
            load_fixture_items("tool_calling", version),
            run_tier(run),
            {"smoke": 5, "standard": 125, "thorough": 125},
        )
        mode = "prompting"
        tools_api_ok = True

        async def score_one(item: dict[str, Any]) -> dict[str, Any]:
            nonlocal mode, tools_api_ok
            openai_tools = _openai_tools(item.get("tools") or [])
            messages = [{"role": "user", "content": item["prompt"]}]
            text = ""
            latency = 0.0
            if client is not None and tools_api_ok and openai_tools and item.get("expected_name"):
                try:
                    text, latency = await chat_once(
                        client,
                        model.name,
                        messages,
                        max_tokens=256,
                        tools=openai_tools,
                    )
                    mode = "tools_api"
                except Exception as exc:
                    if is_infra_error(exc):
                        raise
                    tools_api_ok = False
                    mode = "prompting"
                    text, latency = await chat_once(
                        client, model.name, messages, max_tokens=256
                    )
            else:
                text, latency = await chat_once(
                    client, model.name, messages, max_tokens=256
                )

            name, args, parse_reason = _parse_tool_call(text)
            expect_name = item.get("expected_name")
            match_mode = item.get("match_mode") or "name_args"

            if expect_name is None or match_mode == "irrelevance":
                passed = name is None
                reason = None if passed else "incorrect"
            elif match_mode == "name_only":
                any_names = item.get("expected_names_any") or [expect_name]
                passed = bool(name and name in any_names)
                reason = None if passed else ("unparseable" if parse_reason else "incorrect")
            else:
                if name is None:
                    passed = False
                    reason = parse_reason or "unparseable"
                else:
                    passed = name == expect_name and _args_match(args, item.get("expected_args"))
                    reason = None if passed else "incorrect"

            return {
                "item_id": item["item_id"],
                "passed": passed,
                "raw_answer": text[:1000],
                "latency_ms": latency,
                "reason": reason,
                "extracted": name,
                "detail": {"category": item.get("category"), "mode": mode},
            }

        outcome, _ = await run_quality_items(
            db,
            run,
            "tool_calling:bfcl",
            items,
            score_one,
            metrics={"tool_call_mode": mode},
            title=run_db.suite.name if run_db.suite else "tool_calling",
            sample_text_fn=lambda item, _row: str(item.get("prompt", ""))[:80],
        )
        return outcome

    def metadata(self) -> dict[str, Any]:
        return {"name": "tool_calling", "axis": "tool_calling"}
