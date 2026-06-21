"""Reasoning benchmark runner backed by lm-evaluation-harness."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner
from benchbase.runners.subprocess_utils import make_temp_dir, run_tool


DEFAULT_TASKS = ["gsm8k", "mmlu", "hellaswag", "arc_easy"]


@register_runner("reasoning")
class ReasoningRunner(BenchmarkRunner):
    """Invokes lm-evaluation-harness to run reasoning benchmarks."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        settings = load_settings()
        model_name = run.model.name
        base_url = settings.litellm_base_url.rstrip("/") + "/v1"
        tmpdir = make_temp_dir("benchbase_reasoning_")

        suite_config = json.loads(run.suite.config_json) if run.suite.config_json else {}
        tasks = suite_config.get("tasks", DEFAULT_TASKS)
        num_concurrent = suite_config.get("num_concurrent", 4)
        limit = suite_config.get("limit")

        model_args = f"model={model_name},base_url={base_url},num_concurrent={num_concurrent}"
        if settings.litellm_api_key:
            model_args += f",api_key={settings.litellm_api_key}"

        args = [
            "lm-eval", "run",
            "--model", "local-chat-completions",
            "--model_args", model_args,
            "--tasks", ",".join(tasks),
            "--output_path", str(tmpdir),
            "--log_samples",
        ]
        if limit is not None:
            args.extend(["--limit", str(limit)])

        proc = await run_tool(args, timeout=suite_config.get("timeout", 3600))

        if proc.timed_out:
            raise RuntimeError("lm-eval timed out")
        if proc.returncode != 0:
            raise RuntimeError(f"lm-eval failed (exit {proc.returncode}): {proc.stderr[:500]}")

        results_data = _find_results(tmpdir)

        for task_name, task_results in results_data.items():
            score = (
                task_results.get("acc,none")
                or task_results.get("acc_norm,none")
                or task_results.get("exact_match,strict-match")
            )
            if score is None:
                for k, v in task_results.items():
                    if isinstance(v, (int, float)) and "stderr" not in k:
                        score = v
                        break

            if score is not None:
                score_pct = score * 100 if score <= 1.0 else score

            db.add(Result(
                run_id=run.id,
                task_name=f"reasoning:{task_name}",
                score=score_pct if score is not None else None,
                metrics_json=json.dumps(task_results),
                raw_output_json=json.dumps(task_results),
            ))

        await db.commit()
        shutil.rmtree(tmpdir, ignore_errors=True)

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Reasoning Benchmark",
            "category": "reasoning",
            "description": "lm-evaluation-harness: GSM8K, MMLU, HellaSwag, ARC, and other reasoning suites.",
        }


def _find_results(output_dir: Path) -> dict[str, dict]:
    """Parse the lm-eval output directory structure to extract per-task results."""
    results: dict[str, dict] = {}

    for results_json in output_dir.rglob("results.json"):
        try:
            data = json.loads(results_json.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        task_results = data.get("results", {})
        for task_name, metrics in task_results.items():
            if isinstance(metrics, dict):
                results[task_name] = metrics

    return results
