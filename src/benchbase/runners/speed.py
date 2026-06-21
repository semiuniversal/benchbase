"""Speed benchmark runner backed by llama-benchy."""

from __future__ import annotations

import json
import shutil
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner
from benchbase.runners.subprocess_utils import SubprocessResult, make_temp_dir, run_tool


@register_runner("speed")
class SpeedRunner(BenchmarkRunner):
    """Invokes llama-benchy to measure latency, TTFT, and generation throughput."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        settings = load_settings()
        model_name = run.model.name
        base_url = settings.litellm_base_url.rstrip("/")
        tmpdir = make_temp_dir("benchbase_speed_")
        result_file = tmpdir / "results.json"

        suite_config = json.loads(run.suite.config_json) if run.suite.config_json else {}
        pp = suite_config.get("pp", [512, 2048])
        tg = suite_config.get("tg", [32, 128])
        runs_count = suite_config.get("runs", 3)

        args = [
            "llama-benchy",
            "--base-url", base_url,
            "--model", model_name,
            "--format", "json",
            "--save-result", str(result_file),
            "--latency-mode", "generation",
            "--runs", str(runs_count),
        ]
        for p in pp:
            args.extend(["--pp", str(p)])
        for t in tg:
            args.extend(["--tg", str(t)])

        if settings.litellm_api_key:
            args.extend(["--api-key", settings.litellm_api_key])

        proc = await run_tool(args, timeout=suite_config.get("timeout", 1800))

        if proc.timed_out:
            raise RuntimeError("llama-benchy timed out")
        if proc.returncode != 0:
            raise RuntimeError(f"llama-benchy failed (exit {proc.returncode}): {proc.stderr[:500]}")

        raw = result_file.read_text()
        report = json.loads(raw)
        benchmarks = report.get("benchmarks", [])

        for bm in benchmarks:
            task_parts = []
            if bm.get("is_context_prefill_phase"):
                task_parts.append("ctx_pp")
            else:
                task_parts.append(f"pp{bm['prompt_size']}")
            if bm.get("context_size", 0) > 0:
                task_parts.append(f"@d{bm['context_size']}")
            if bm.get("concurrency", 1) > 1:
                task_parts.append(f"(c{bm['concurrency']})")

            pp_metric = bm.get("pp_throughput")
            if pp_metric:
                db.add(Result(
                    run_id=run.id,
                    task_name=f"speed:{''.join(task_parts)}",
                    score=pp_metric["mean"],
                    metrics_json=json.dumps({
                        "type": "pp",
                        "throughput_mean": pp_metric["mean"],
                        "throughput_std": pp_metric["std"],
                        "ttfr": _extract(bm, "ttfr"),
                        "est_ppt": _extract(bm, "est_ppt"),
                        "e2e_ttft": _extract(bm, "e2e_ttft"),
                    }),
                    raw_output_json=json.dumps(bm),
                ))

            tg_metric = bm.get("tg_throughput")
            if tg_metric:
                tg_task = f"speed:tg{bm['response_size']}"
                if bm.get("context_size", 0) > 0:
                    tg_task += f"@d{bm['context_size']}"
                if bm.get("concurrency", 1) > 1:
                    tg_task += f"(c{bm['concurrency']})"
                peak = bm.get("peak_throughput")
                db.add(Result(
                    run_id=run.id,
                    task_name=tg_task,
                    score=tg_metric["mean"],
                    metrics_json=json.dumps({
                        "type": "tg",
                        "throughput_mean": tg_metric["mean"],
                        "throughput_std": tg_metric["std"],
                        "peak_mean": peak["mean"] if peak else None,
                        "peak_std": peak["std"] if peak else None,
                    }),
                    raw_output_json=json.dumps(bm),
                ))

        await db.commit()

        shutil.rmtree(tmpdir, ignore_errors=True)

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Speed Benchmark",
            "category": "speed",
            "description": "llama-benchy: latency, TTFT, prompt processing, and generation throughput.",
        }


def _extract(bm: dict, key: str) -> dict | None:
    val = bm.get(key)
    if val is None:
        return None
    return {"mean": val["mean"], "std": val["std"]}
