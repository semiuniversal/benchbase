"""Tool-use evaluation runner backed by LiteBench agent mode."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner
from benchbase.runners.subprocess_utils import run_tool


AGENT_TASKS = ["arc", "truthfulqa"]


@register_runner("tool_use")
class ToolUseRunner(BenchmarkRunner):
    """Invokes litebench in agent mode for tool-use and instruction-following evaluation."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        settings = load_settings()
        model_name = run.model.name
        base_url = settings.litellm_base_url.rstrip("/")

        suite_config = json.loads(run.suite.config_json) if run.suite.config_json else {}
        tasks = suite_config.get("tasks", AGENT_TASKS)
        n_samples = suite_config.get("n_samples", 30)

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
                raise RuntimeError(f"litebench agent {task} timed out")
            if proc.returncode != 0:
                raise RuntimeError(
                    f"litebench agent {task} failed (exit {proc.returncode}): {proc.stderr[:500]}"
                )

            score = _parse_score(proc.stdout)

            db.add(Result(
                run_id=run.id,
                task_name=f"tool_use:{task}",
                score=score,
                metrics_json=json.dumps({
                    "task": task,
                    "n_samples": n_samples,
                    "success_rate": score,
                }),
                raw_output_json=json.dumps({
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-500:],
                }),
            ))

        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Tool Use Benchmark",
            "category": "tool_use",
            "description": "LiteBench agent mode: tool-call correctness and instruction following.",
        }


def _parse_score(stdout: str) -> float | None:
    """Extract a success rate / accuracy from litebench agent-mode stdout."""
    for line in reversed(stdout.splitlines()):
        match = re.search(r"(\d+(?:\.\d+)?)\s*%?\s*$", line.strip().rstrip("|").strip())
        if match:
            return float(match.group(1))

    match = re.search(r"(?:accuracy|success|score|pass)[:\s]+(\d+(?:\.\d+)?)", stdout, re.I)
    if match:
        return float(match.group(1))

    return None
