"""Coding benchmark runner backed by LiteBench."""

from __future__ import annotations

import json
import re
import shutil
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner
from benchbase.runners.subprocess_utils import make_temp_dir, run_tool


@register_runner("coding")
class CodingRunner(BenchmarkRunner):
    """Invokes litebench to run HumanEval and other coding benchmarks."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        settings = load_settings()
        model_name = run.model.name
        base_url = settings.litellm_base_url.rstrip("/")

        suite_config = json.loads(run.suite.config_json) if run.suite.config_json else {}
        tasks = suite_config.get("tasks", ["humaneval"])
        n_samples = suite_config.get("n_samples", 50)

        env: dict[str, str] = {}
        if settings.litellm_api_key:
            env["OPENAI_API_KEY"] = settings.litellm_api_key
        env["OPENAI_API_BASE"] = base_url

        for task in tasks:
            args = [
                "litebench", "run", task,
                "-m", model_name,
                "-n", str(n_samples),
            ]

            proc = await run_tool(
                args,
                timeout=suite_config.get("timeout", 1800),
                env=env,
            )

            if proc.timed_out:
                raise RuntimeError(f"litebench {task} timed out")
            if proc.returncode != 0:
                raise RuntimeError(
                    f"litebench {task} failed (exit {proc.returncode}): {proc.stderr[:500]}"
                )

            score = _parse_litebench_score(proc.stdout)

            db.add(Result(
                run_id=run.id,
                task_name=f"coding:{task}",
                score=score,
                metrics_json=json.dumps({
                    "task": task,
                    "n_samples": n_samples,
                    "pass_rate": score,
                }),
                raw_output_json=json.dumps({
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-500:],
                }),
            ))

        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Coding Benchmark",
            "category": "coding",
            "description": "LiteBench: HumanEval and other code-generation benchmarks.",
        }


def _parse_litebench_score(stdout: str) -> float | None:
    """Extract a pass rate / accuracy from litebench stdout.

    LiteBench prints a table with columns including a percentage score.
    We look for patterns like "89.0" in the results row.
    """
    for line in reversed(stdout.splitlines()):
        match = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*$", line.strip().rstrip("|").strip())
        if match:
            return float(match.group(1))

    match = re.search(r"(?:accuracy|pass_rate|score|pass@1)[:\s]+(\d+(?:\.\d+)?)", stdout, re.I)
    if match:
        return float(match.group(1))

    return None
