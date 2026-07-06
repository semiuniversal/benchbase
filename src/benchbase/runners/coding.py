"""Coding benchmark runner backed by LiteBench."""

from __future__ import annotations

import json
import sys
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.runners.run_metadata import metadata_int
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner
from benchbase.runners.litebench_parse import (
    count_litebench_backend_errors,
    parse_litebench_accuracy,
    parse_litebench_pass_counts,
)
from benchbase.runners.subprocess_utils import run_tool
from benchbase.run_log import RunLogManager


@register_runner("coding")
class CodingRunner(BenchmarkRunner):
    """Invokes litebench to run HumanEval and other coding benchmarks."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        settings = load_settings()
        model_name = f"openai/{run.model.name}"
        base_url = settings.litellm_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"

        suite_config = json.loads(run.suite.config_json) if run.suite.config_json else {}
        tasks = suite_config.get("tasks", ["humaneval"])
        n_samples = metadata_int(run, "n_samples", suite_config, 10)

        env: dict[str, str] = {}
        if settings.litellm_api_key:
            env["OPENAI_API_KEY"] = settings.litellm_api_key
        env["OPENAI_API_BASE"] = base_url

        llm_timeout = suite_config.get("llm_timeout", settings.litebench_timeout_seconds)
        concurrency = suite_config.get("concurrency", 1)
        max_tokens = suite_config.get("max_tokens", 1024)

        for task in tasks:
            RunLogManager.log(
                run.id,
                f"Starting coding task {task}: {n_samples} samples, concurrency={concurrency}",
            )
            args = [
                sys.executable, "-m", "benchbase.runners.litebench_runner",
                "run", task,
                "-m", model_name,
                "-n", str(n_samples),
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
                    f"litebench {task} failed (exit {proc.returncode}): {proc.stderr[:500]}"
                )

            combined = f"{proc.stdout}\n{proc.stderr}"
            score = parse_litebench_accuracy(combined)
            if score is None:
                raise RuntimeError(
                    f"litebench {task} finished but no accuracy score found in output"
                )

            pass_counts = parse_litebench_pass_counts(combined)
            backend_errors = count_litebench_backend_errors(combined)

            metrics: dict[str, Any] = {
                "task": task,
                "n_samples": n_samples,
                "pass_rate": score,
            }
            if pass_counts:
                metrics["passed"] = pass_counts[0]
                metrics["total"] = pass_counts[1]
            if backend_errors:
                metrics["backend_errors"] = backend_errors

            db.add(Result(
                run_id=run.id,
                task_name=f"coding:{task}",
                score=score,
                metrics_json=json.dumps(metrics),
                raw_output_json=json.dumps({
                    "stdout_head": proc.stdout[:4000],
                    "stdout_tail": proc.stdout[-4000:],
                    "stderr_tail": proc.stderr[-1000:],
                }),
            ))

        await db.commit()

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Coding Benchmark",
            "category": "coding",
            "description": "LiteBench: HumanEval and other code-generation benchmarks.",
        }


