"""Coding runner — sandboxed subprocess execution of model solutions."""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
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


def _extract_python(text: str) -> str:
    m = re.search(r"```(?:python)?\s*\n([\s\S]*?)```", text)
    if m:
        return m.group(1)
    return text


async def _exec_solve(code: str, entry: str, arg: str, timeout: float = 2.0) -> tuple[bool, str]:
    script = (
        code
        + "\n"
        + f"if __name__ == '__main__':\n"
        + f"    print({entry}({arg}))\n"
    )
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sol.py"
        path.write_text(script, encoding="utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return False, "timeout"
            out = stdout.decode().strip()
            if proc.returncode != 0:
                return False, stderr.decode()[:500]
            return True, out
        except Exception as exc:
            return False, str(exc)


@register_runner("coding")
class CodingRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model)])
        model: Model = run_db.model
        client = LiteLLMClient(base_url=model.endpoint_url)
        items = select_tier_items(
            load_fixture_items("coding"),
            run_tier(run),
            {"smoke": 5, "standard": 40, "thorough": 40},
        )
        rows: list[dict[str, Any]] = []
        for item in items:
            text, latency = await chat_once(
                client,
                model.name,
                [{"role": "user", "content": item["prompt"]}],
                max_tokens=512,
            )
            code = _extract_python(text)
            entry = item.get("entry_point", "solve")
            passed = True
            detail = []
            for test in item.get("tests") or []:
                ok, out = await _exec_solve(code, entry, test.get("input", "0"))
                expect = str(test.get("output", "")).strip()
                match = ok and out.strip() == expect
                detail.append({"ok": match, "out": out, "expect": expect})
                if not match:
                    passed = False
                    break
            rows.append(
                {
                    "item_id": item["item_id"],
                    "passed": passed,
                    "raw_answer": code[:2000],
                    "latency_ms": latency,
                    "detail": detail,
                }
            )
        await persist_axis_result(db, run, "coding:livecodebench", rows)
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "coding", "axis": "coding"}
