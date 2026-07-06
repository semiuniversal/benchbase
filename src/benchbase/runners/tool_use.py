"""Tool-use evaluation runner backed by LiteBench agent mode."""

from __future__ import annotations

import json
import sys
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.runners.run_metadata import is_full_benchmark, metadata_int
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner
from benchbase.runners.litebench_parse import parse_litebench_accuracy
from benchbase.runners.subprocess_utils import run_tool
from benchbase.run_log import RunLogManager


AGENT_TASKS = ["arc", "truthfulqa"]


@register_runner("tool_use")
class ToolUseRunner(BenchmarkRunner):
    """Invokes litebench in agent mode for tool-use and instruction-following evaluation."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        settings = load_settings()
        model_name = f"openai/{run.model.name}"
        base_url = settings.litellm_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"

        suite_config = json.loads(run.suite.config_json) if run.suite.config_json else {}
        tasks = suite_config.get("tasks", AGENT_TASKS)
        n_samples = metadata_int(run, "n_samples", suite_config, 8)

        env: dict[str, str] = {}
        if settings.litellm_api_key:
            env["OPENAI_API_KEY"] = settings.litellm_api_key
        env["OPENAI_API_BASE"] = base_url

        llm_timeout = suite_config.get("llm_timeout", settings.litebench_timeout_seconds)
        concurrency = suite_config.get("concurrency", 1)
        max_tokens = suite_config.get("max_tokens", 512)
        task_errors: list[str] = []

        for task in tasks:
            task_n = (
                n_samples
                if is_full_benchmark(run) or task != "truthfulqa"
                else min(n_samples, 8)
            )
            RunLogManager.log(
                run.id,
                f"Starting tool-use task {task}: {task_n} samples, concurrency={concurrency}",
            )
            try:
                args = [
                    sys.executable, "-m", "benchbase.runners.litebench_runner",
                    "run", task,
                    "-m", model_name,
                    "-n", str(task_n),
                    "-c", str(concurrency),
                    "--max-tokens", str(max_tokens),
                    "--timeout", str(llm_timeout),
                    "--no-save",
                ]

                proc = await run_tool(
                    args,
                    timeout=suite_config.get("timeout", 1800),
                    env=env,
                    run_id=run.id,
                )

                if proc.timed_out:
                    raise RuntimeError(f"litebench {task} timed out")
                if proc.cancelled:
                    raise RuntimeError("cancelled")
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"litebench {task} failed (exit {proc.returncode}): "
                        f"{proc.stderr[:500]}"
                    )

                combined = f"{proc.stdout}\n{proc.stderr}"
                score = parse_litebench_accuracy(combined)
                if score is None:
                    raise RuntimeError(
                        f"litebench {task} finished but no accuracy score found in output"
                    )

                db.add(Result(
                    run_id=run.id,
                    task_name=f"tool_use:{task}",
                    score=score,
                    metrics_json=json.dumps({
                        "task": task,
                        "n_samples": task_n,
                        "success_rate": score,
                    }),
                    raw_output_json=json.dumps({
                        "stdout_head": proc.stdout[:4000],
                        "stdout_tail": proc.stdout[-4000:],
                        "stderr_tail": proc.stderr[-1000:],
                    }),
                ))
                await db.commit()
            except Exception as exc:
                if str(exc) == "cancelled":
                    raise
                task_errors.append(f"{task}: {exc}")
                db.add(Result(
                    run_id=run.id,
                    task_name=f"tool_use:{task}",
                    score=None,
                    metrics_json=json.dumps({
                        "task": task,
                        "n_samples": task_n,
                        "error": str(exc),
                    }),
                    raw_output_json=json.dumps({
                        "stderr_tail": str(exc)[:2000],
                    }),
                ))
                await db.commit()

        if task_errors and len(task_errors) == len(tasks):
            raise RuntimeError("; ".join(task_errors))

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Tool Use Benchmark",
            "category": "tool_use",
            "description": "LiteBench agent mode: tool-call correctness and instruction following.",
        }


