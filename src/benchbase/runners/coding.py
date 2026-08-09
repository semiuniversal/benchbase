"""Coding runner — sandboxed stdin/stdout or function execution."""

from __future__ import annotations

import asyncio
import re
import tempfile
from pathlib import Path
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


def _extract_python(text: str) -> str | None:
    if not text or not text.strip():
        return None
    m = re.search(r"```(?:python)?\s*\n([\s\S]*?)```", text)
    if m:
        body = m.group(1).strip()
        # Reject empty / stub fences from echoed prompts.
        if not body or len(body) < 8:
            return None
        return body
    # Reject echo-of-prompt style blobs that aren't code.
    if text.count("\n") < 2:
        return None
    if "Solve the following programming problem" in text:
        return None
    if "def " in text or "print(" in text or "input(" in text:
        return text
    return None


async def _exec_stdin(code: str, stdin_data: str, timeout: float = 3.0) -> tuple[str, str, str]:
    """Returns (status, stdout, detail) status in {passed_run, failed, harness_error, timeout}."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "sol.py"
        path.write_text(code, encoding="utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3",
                str(path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(stdin_data.encode()), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return "timeout", "", "timeout"
            out = stdout.decode(errors="replace")
            err = stderr.decode(errors="replace")[:500]
            if proc.returncode != 0:
                return "failed", out, err or f"exit {proc.returncode}"
            return "passed_run", out, ""
        except Exception as exc:
            return "harness_error", "", str(exc)


async def _exec_solve(code: str, entry: str, arg: str, timeout: float = 2.0) -> tuple[str, str, str]:
    script = code + "\n" + f"if __name__ == '__main__':\n    print({entry}({arg}))\n"
    return await _exec_stdin(script, "", timeout=timeout)


@register_runner("coding")
class CodingRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)])
        model: Model = run_db.model
        client = None if is_control_model_name(model.name) else LiteLLMClient(base_url=model.endpoint_url)
        version = suite_version_for_run(run_db)
        items = select_tier_items(
            load_fixture_items("coding", version),
            run_tier(run),
            {"smoke": 5, "standard": 40, "thorough": 45},
        )
        progress = AxisProgressLog(
            title=run_db.suite.name if run_db.suite else "coding",
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
                    max_tokens=1200,
                )
                code = _extract_python(text)
                tests = item.get("tests") or []
                if not tests:
                    row = {
                        "item_id": item["item_id"],
                        "passed": False,
                        "raw_answer": (text or "")[:2000],
                        "latency_ms": latency,
                        "reason": "harness_error",
                        "detail": {"error": "empty tests"},
                    }
                    rows.append(row)
                    progress.record(row, sample_text=str(item.get("prompt", ""))[:80])
                    continue
                if code is None:
                    row = {
                        "item_id": item["item_id"],
                        "passed": False,
                        "raw_answer": (text or "")[:2000],
                        "latency_ms": latency,
                        "reason": "unparseable",
                    }
                    rows.append(row)
                    progress.record(row, sample_text=str(item.get("prompt", ""))[:80])
                    continue

                harness = item.get("harness") or "function"
                entry = item.get("entry_point") or "solve"
                detail = []
                passed = True
                fail_reason = "incorrect"
                for test in tests:
                    expect = str(test.get("output", "")).rstrip("\n")
                    if harness == "stdin":
                        status, out, info = await _exec_stdin(code, str(test.get("input", "")))
                    else:
                        status, out, info = await _exec_solve(code, entry, test.get("input", "0"))
                    if status == "timeout":
                        passed = False
                        fail_reason = "timeout"
                        detail.append({"status": status, "info": info})
                        break
                    if status == "harness_error":
                        passed = False
                        fail_reason = "harness_error"
                        detail.append({"status": status, "info": info})
                        break
                    match = status == "passed_run" and out.rstrip("\n") == expect
                    detail.append(
                        {"status": status, "out": out[:200], "expect": expect[:200], "ok": match}
                    )
                    if not match:
                        passed = False
                        fail_reason = "incorrect"
                        break
                row = {
                    "item_id": item["item_id"],
                    "passed": passed,
                    "raw_answer": code[:2000],
                    "latency_ms": latency,
                    "reason": None if passed else fail_reason,
                    "detail": detail,
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
        result = await persist_axis_result(db, run, "coding:livecodebench", rows)
        progress.finish(result.score)
        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {"name": "coding", "axis": "coding"}
