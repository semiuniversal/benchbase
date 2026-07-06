"""Speed benchmark runner backed by llama-benchy."""

from __future__ import annotations

import json
import shutil
import sys
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.llama_benchy_corpus_patch import default_corpus_source
from benchbase.runners.registry import register_runner
from benchbase.runners.run_metadata import metadata_int
from benchbase.runners.subprocess_utils import make_temp_dir, run_tool
from benchbase.run_log import RunLogManager


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

        book_url = suite_config.get("book_url", default_corpus_source())
        args.extend(["--book-url", book_url])

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

            tg_metric = bm.get("output_tg_throughput") or thinking.get("output_tg_throughput")
            if tg_metric and tg_metric.get("mean") is not None:
                output_ttft = bm.get("output_ttft_ms") or thinking.get("output_ttft_ms")
                db.add(Result(
                    run_id=run.id,
                    task_name=f"speed:output_tg{bm['response_size']}{suffix}",
                    score=tg_metric["mean"],
                    metrics_json=json.dumps({
                        "type": "output_tg",
                        "throughput_mean": tg_metric["mean"],
                        "throughput_std": tg_metric.get("std"),
                        "output_ttft_ms": output_ttft,
                    }),
                    raw_output_json=json.dumps(bm),
                ))

            _store_output_speed_results(db, run.id, bm, thinking, suffix)

        await db.commit()

        has_speed = any(
            (bm.get("benchbase_thinking") or {}).get("output_completion_ms")
            or (bm.get("benchbase_thinking") or {}).get("output_tg_throughput")
            or bm.get("pp_throughput")
            for bm in benchmarks
        )
        has_output_tg = any(
            (bm.get("benchbase_thinking") or {}).get("output_tg_throughput")
            or bm.get("output_tg_throughput")
            for bm in benchmarks
        )
        if has_speed and not has_output_tg:
            RunLogManager.log(
                run.id,
                "Note: model produced no visible output tokens — speed rank uses "
                "wall-clock time only. Re-run with a model that emits content, or "
                "compare thinking throughput separately (not used for speed rank).",
            )
        if not has_speed:
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
                "Time to usable output (primary) and output-only tok/s. "
                "Thinking streams are not counted toward speed; use reasoning/coding for quality."
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


def _store_output_speed_results(
    db: AsyncSession,
    run_id: int,
    bm: dict[str, Any],
    thinking: dict[str, Any],
    suffix: str,
) -> None:
    """Persist output-only speed metrics. Thinking streams are not stored here."""
    response_size = bm["response_size"]

    completion = thinking.get("output_completion_ms")
    if completion and completion.get("mean") is not None:
        db.add(Result(
            run_id=run_id,
            task_name=f"speed:output_completion{response_size}{suffix}",
            score=completion["mean"],
            metrics_json=json.dumps({
                "type": "output_completion",
                "unit": "ms",
                "mean": completion["mean"],
                "std": completion.get("std"),
                "output_generation_ms": thinking.get("output_generation_ms"),
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
