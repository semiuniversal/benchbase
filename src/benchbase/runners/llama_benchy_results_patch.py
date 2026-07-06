"""Inject BenchBase thinking/output split metrics into llama-benchy JSON reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from llama_benchy.client import RequestResult
from llama_benchy.results import BenchmarkResults

from benchbase.runners.llama_benchy_stream import (
    effective_visible_throughput,
    throughput_from_timestamps,
)


def _metric(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "values": values,
    }


def aggregate_thinking_metrics(
    run_results: list[list[RequestResult]],
) -> dict[str, dict[str, Any] | None]:
    """Summarize output latency, thinking streams, and decode throughput."""
    think_speeds: list[float] = []
    think_ttfts_ms: list[float] = []
    think_durations_ms: list[float] = []
    think_token_counts: list[float] = []
    output_ttfts_ms: list[float] = []
    output_speeds: list[float] = []
    output_decode_speeds: list[float] = []
    output_completions_ms: list[float] = []
    output_generations_ms: list[float] = []
    output_token_counts: list[float] = []
    think_times_ms: list[float] = []
    wall_clocks_ms: list[float] = []

    for batch in run_results:
        for res in batch:
            if not res or res.error:
                continue

            if res.end_ts and res.start_ts:
                wall_clocks_ms.append((res.end_ts - res.start_ts) * 1000)

            output_ts = res.token_timestamps or []
            if output_ts and res.first_token_ts is not None:
                output_completions_ms.append((output_ts[-1] - res.start_ts) * 1000)
                output_generations_ms.append((output_ts[-1] - res.first_token_ts) * 1000)
                output_ttfts_ms.append((res.first_token_ts - res.start_ts) * 1000)
            elif res.end_ts:
                # No visible output tokens — count full request time.
                output_completions_ms.append((res.end_ts - res.start_ts) * 1000)

            total_visible = getattr(res, "total_tokens", None) or None
            eff_tps, _, _, visible_count = effective_visible_throughput(
                output_ts,
                start_ts=res.start_ts,
                first_ts=res.first_token_ts,
                total_tokens=total_visible,
            )
            if eff_tps is not None:
                output_speeds.append(eff_tps)
            if visible_count:
                output_token_counts.append(float(visible_count))

            reasoning_total = getattr(res, "reasoning_total_tokens", 0) or 0
            if reasoning_total and res.first_token_ts is not None:
                think_times_ms.append((res.first_token_ts - res.start_ts) * 1000)
            elif reasoning_total and res.end_ts and res.start_ts and not output_ts:
                think_times_ms.append((res.end_ts - res.start_ts) * 1000)

            decode_tps, _, _ = throughput_from_timestamps(
                output_ts,
                start_ts=res.start_ts,
                first_ts=res.first_token_ts,
                total_tokens=total_visible,
            )
            if decode_tps is not None:
                output_decode_speeds.append(decode_tps)

            reasoning_ts = getattr(res, "reasoning_token_timestamps", None) or []
            first_reasoning = getattr(res, "first_reasoning_token_ts", None)
            if first_reasoning is not None:
                think_ttfts_ms.append((first_reasoning - res.start_ts) * 1000)

            think_tps, _, think_duration = throughput_from_timestamps(
                reasoning_ts,
                start_ts=res.start_ts,
                first_ts=first_reasoning,
                total_tokens=getattr(res, "reasoning_total_tokens", None) or None,
            )
            if think_tps is not None:
                think_speeds.append(think_tps)
            if think_duration is not None:
                think_durations_ms.append(think_duration * 1000)
            if reasoning_total:
                think_token_counts.append(float(reasoning_total))

    return {
        "output_completion_ms": _metric(output_completions_ms),
        "output_generation_ms": _metric(output_generations_ms),
        "wall_clock_ms": _metric(wall_clocks_ms),
        "output_tg_throughput": _metric(output_speeds),
        "output_decode_tg_throughput": _metric(output_decode_speeds),
        "output_token_count": _metric(output_token_counts),
        "think_time_ms": _metric(think_times_ms),
        "think_tg_throughput": _metric(think_speeds),
        "think_ttft_ms": _metric(think_ttfts_ms),
        "think_duration_ms": _metric(think_durations_ms),
        "think_token_count": _metric(think_token_counts),
        "output_ttft_ms": _metric(output_ttfts_ms),
    }


def _has_benchbase_metrics(metrics: dict[str, dict[str, Any] | None]) -> bool:
    return any(metrics.get(key) for key in metrics)


def apply_llama_benchy_results_patch() -> None:
    """Extend llama-benchy result export with BenchBase thinking metrics."""
    if getattr(BenchmarkResults, "_benchbase_results_patch_applied", False):
        return

    original_init = BenchmarkResults.__init__
    original_add = BenchmarkResults.add
    original_save_report = BenchmarkResults.save_report

    def init_patched(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._benchbase_thinking: list[dict[str, dict[str, Any] | None]] = []

    def add_patched(self, *args, **kwargs):
        run_results = kwargs.get("run_results")
        if run_results is None and len(args) >= 6:
            run_results = args[5]
        thinking = aggregate_thinking_metrics(run_results or [])
        original_add(self, *args, **kwargs)
        self._benchbase_thinking.append(thinking)

    def save_report_patched(self, path, result_format, max_concurrency):
        original_save_report(self, path, result_format, max_concurrency)
        if result_format != "json" or not path:
            return

        report_path = Path(path)
        if not report_path.exists():
            return

        data = json.loads(report_path.read_text())
        benchmarks = data.get("benchmarks", [])
        for index, benchmark in enumerate(benchmarks):
            if index >= len(self._benchbase_thinking):
                break
            thinking = self._benchbase_thinking[index]
            if _has_benchbase_metrics(thinking):
                benchmark["benchbase_thinking"] = thinking
            output_ttft = thinking.get("output_ttft_ms")
            if output_ttft and not benchmark.get("e2e_ttft"):
                benchmark["output_ttft_ms"] = output_ttft
            output_tg = thinking.get("output_tg_throughput")
            if output_tg:
                benchmark["output_tg_throughput"] = output_tg

        report_path.write_text(json.dumps(data, indent=2))

    BenchmarkResults.__init__ = init_patched
    BenchmarkResults.add = add_patched
    BenchmarkResults.save_report = save_report_patched
    BenchmarkResults._benchbase_results_patch_applied = True
