"""Instruction-following (IFEval-style) rule verification."""

from __future__ import annotations

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
    persist_axis_result,
    run_tier,
    select_tier_items,
    suite_version_for_run,
)
from benchbase.runners.progress_log import AxisProgressLog
from benchbase.runners.registry import register_runner


def check_rule(text: str, rule: dict[str, Any]) -> tuple[bool, str | None]:
    if not text or not text.strip():
        return False, "unparseable"
    if not rule:
        return False, "scorer-error"
    rtype = rule.get("type")
    if rtype == "word_count":
        words = [w for w in text.strip().split() if w]
        ok = len(words) == int(rule.get("n", -1))
        return ok, None if ok else "incorrect"
    if rtype == "forbidden_words":
        lower = text.lower()
        for w in rule.get("words") or []:
            if str(w).lower() in lower:
                return False, "incorrect"
        return True, None
    if rtype == "required_words":
        lower = text.lower()
        for w in rule.get("words") or []:
            if str(w).lower() not in lower:
                return False, "incorrect"
        return True, None
    if rtype == "all_caps":
        letters = [c for c in text if c.isalpha()]
        ok = bool(letters) and all(c.isupper() for c in letters)
        return ok, None if ok else "incorrect"
    if rtype == "all_lowercase":
        letters = [c for c in text if c.isalpha()]
        ok = bool(letters) and all(c.islower() for c in letters)
        return ok, None if ok else "incorrect"
    if rtype == "no_comma":
        ok = "," not in text
        return ok, None if ok else "incorrect"
    if rtype == "ends_with":
        val = str(rule.get("value") or "")
        ok = text.rstrip().endswith(val)
        return ok, None if ok else "incorrect"
    if rtype == "wrapped_quotes":
        s = text.strip()
        ok = len(s) >= 2 and s[0] == '"' and s[-1] == '"'
        return ok, None if ok else "incorrect"
    if rtype == "min_highlights":
        n = len(re.findall(r"\*[^*]+\*", text))
        ok = n >= int(rule.get("n", 1))
        return ok, None if ok else "incorrect"
    if rtype == "has_title":
        ok = bool(re.search(r"<<.*>>", text))
        return ok, None if ok else "incorrect"
    if rtype == "paragraph_count":
        parts = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
        ok = len(parts) == int(rule.get("n", -1))
        return ok, None if ok else "incorrect"
    if rtype == "sentence_count":
        sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
        ok = len(sentences) == int(rule.get("n", -1))
        return ok, None if ok else "incorrect"
    if rtype == "placeholder_count":
        n = len(re.findall(r"\[[^\]]+\]", text))
        ok = n >= int(rule.get("n", 1))
        return ok, None if ok else "incorrect"
    return False, "scorer-error"


@register_runner("instruction")
class InstructionRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)])
        model: Model = run_db.model
        client = None if is_control_model_name(model.name) else LiteLLMClient(base_url=model.endpoint_url)
        version = suite_version_for_run(run_db)
        items = select_tier_items(
            load_fixture_items("instruction", version),
            run_tier(run),
            {"smoke": 5, "standard": 50, "thorough": 50},
        )
        progress = AxisProgressLog(
            title=run_db.suite.name if run_db.suite else "instruction",
            total=len(items),
            tier=run_tier(run).value,
        )
        rows: list[dict[str, Any]] = []
        for item in items:
            try:
                text, latency = await chat_once(
                    client,
                    model.name,
                    [{"role": "user", "content": item["prompt"]}],
                    max_tokens=256,
                )
                if text.strip() == (item.get("prompt") or "").strip():
                    passed, reason = False, "incorrect"
                elif "FORBIDDEN_WORD_xyzzy" in text or "THIS_IS_WRONG" in text:
                    passed, reason = False, "incorrect"
                else:
                    passed, reason = check_rule(text, item.get("rule") or {})
                row = {
                    "item_id": item["item_id"],
                    "passed": passed if reason != "scorer-error" else None,
                    "raw_answer": text[:1000],
                    "latency_ms": latency,
                    "reason": reason,
                    "scorer_error": reason == "scorer-error",
                    "detail": {"rule": item.get("rule")},
                }
            except Exception as exc:
                row = {
                    "item_id": item["item_id"],
                    "passed": None,
                    "raw_answer": str(exc)[:500],
                    "scorer_error": True,
                    "reason": "scorer-error",
                }
            rows.append(row)
            progress.record(row, sample_text=str(item.get("prompt", ""))[:80])
        result = await persist_axis_result(db, run, "instruction:ifeval", rows)
        progress.finish(result.score)
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "instruction", "axis": "instruction"}
