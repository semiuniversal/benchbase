"""Speed benchmark runner backed by llama-benchy."""

from __future__ import annotations

import json
import shutil
import sys
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.runners.run_metadata import metadata_int
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner
from benchbase.runners.subprocess_utils import make_temp_dir, run_tool


@register_runner("speed")
class SpeedRunner(BenchmarkRunner):
    """Invokes llama-benchy to measure latency, TTFT, and generation throughput."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        settings = load_settings()
        model_name = run.model.name
        base_url = settings.litellm_base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"
        tmpdir = make_temp_dir("benchbase_speed_")
        result_file = tmpdir / "results.json"

        suite_config = json.loads(run.suite.config_json) if run.suite.config_json else {}
        pp = suite_config.get("pp", [128])
        tg = suite_config.get("tg", [32])
        runs_count = metadata_int(run, "runs", suite_config, 1)

        args = [
            sys.executable, "-m", "benchbase.runners.llama_benchy_runner",
            "--base-url", base_url,
            "--model", model_name,
            "--tokenizer", suite_config.get("tokenizer", "gpt2"),
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

        proc = await run_tool(
            args,
            timeout=suite_config.get("timeout", 1800),
            run_id=run.id,
        )

        if proc.timed_out:
            raise RuntimeError("llama-benchy timed out")
        if proc.cancelled:
            raise RuntimeError("cancelled")
        if proc.returncode != 0:
            raise RuntimeError(f"llama-benchy failed (exit {proc.returncode}): {proc.stderr[:500]}")

        raw = result_file.read_text()
        report = json.loads(raw)
        benchmarks = report.get("benchmarks", [])

        for bm in benchmarks:
            suffix = _task_suffix(bm)
            thinking = bm.get("benchbase_thinking") or {}

            pp_metric = bm.get("pp_throughput")
            if pp_metric:
                db.add(Result(
                    run_id=run.id,
                    task_name=f"speed:{_pp_task_name(bm)}",
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
                peak = bm.get("peak_throughput")
                output_ttft = bm.get("output_ttft_ms") or thinking.get("output_ttft_ms")
                db.add(Result(
                    run_id=run.id,
                    task_name=f"speed:tg{bm['response_size']}{suffix}",
                    score=tg_metric["mean"],
                    metrics_json=json.dumps({
                        "type": "output_tg",
                        "throughput_mean": tg_metric["mean"],
                        "throughput_std": tg_metric["std"],
                        "peak_mean": peak["mean"] if peak else None,
                        "peak_std": peak["std"] if peak else None,
                        "output_ttft_ms": output_ttft,
                    }),
                    raw_output_json=json.dumps(bm),
                ))

            _store_thinking_results(db, run.id, bm, thinking, suffix)

        await db.commit()

        if not any(bm.get("pp_throughput") or bm.get("tg_throughput") for bm in benchmarks):
            raise RuntimeError(
                "Benchmark produced no throughput metrics (model returned empty completions). "
                "Try again or pick a different model."
            )

        shutil.rmtree(tmpdir, ignore_errors=True)

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Speed Benchmark",
            "category": "speed",
            "description": (
                "llama-benchy: output throughput, thinking throughput, TTFT, "
                "and prompt processing metrics."
            ),
        }


def _task_suffix(bm: dict[str, Any]) -> str:
    parts: list[str] = []
    if bm.get("context_size", 0) > 0:
        parts.append(f"@d{bm['context_size']}")
    if bm.get("concurrency", 1) > 1:
        parts.append(f"(c{bm['concurrency']})")
    return "".join(parts)


def _pp_task_name(bm: dict[str, Any]) -> str:
    parts: list[str] = []
    if bm.get("is_context_prefill_phase"):
        parts.append("ctx_pp")
    else:
        parts.append(f"pp{bm['prompt_size']}")
    parts.append(_task_suffix(bm))
    return "".join(parts)


def _store_thinking_results(
    db: AsyncSession,
    run_id: int,
    bm: dict[str, Any],
    thinking: dict[str, Any],
    suffix: str,
) -> None:
    response_size = bm["response_size"]
    base_name = f"speed:think_tg{response_size}{suffix}"

    think_tg = thinking.get("think_tg_throughput")
    if think_tg and think_tg.get("mean") is not None:
        db.add(Result(
            run_id=run_id,
            task_name=base_name,
            score=think_tg["mean"],
            metrics_json=json.dumps({
                "type": "think_tg",
                "throughput_mean": think_tg["mean"],
                "throughput_std": think_tg.get("std"),
                "think_ttft_ms": thinking.get("think_ttft_ms"),
                "think_duration_ms": thinking.get("think_duration_ms"),
                "think_token_count": thinking.get("think_token_count"),
            }),
            raw_output_json=json.dumps(thinking),
        ))

    think_ttft = thinking.get("think_ttft_ms")
    if think_ttft and think_ttft.get("mean") is not None:
        db.add(Result(
            run_id=run_id,
            task_name=f"speed:think_ttft{response_size}{suffix}",
            score=think_ttft["mean"],
            metrics_json=json.dumps({
                "type": "think_ttft",
                "unit": "ms",
                "mean": think_ttft["mean"],
                "std": think_ttft.get("std"),
            }),
            raw_output_json=json.dumps(thinking),
        ))

    output_ttft = thinking.get("output_ttft_ms") or bm.get("output_ttft_ms")
    if output_ttft and output_ttft.get("mean") is not None:
        db.add(Result(
            run_id=run_id,
            task_name=f"speed:output_ttft{response_size}{suffix}",
            score=output_ttft["mean"],
            metrics_json=json.dumps({
                "type": "output_ttft",
                "unit": "ms",
                "mean": output_ttft["mean"],
                "std": output_ttft.get("std"),
            }),
            raw_output_json=json.dumps(thinking or {"output_ttft_ms": output_ttft}),
        ))


def _extract(bm: dict, key: str) -> dict | None:
    val = bm.get(key)
    if val is None:
        return None
    return {"mean": val["mean"], "std": val["std"]}
