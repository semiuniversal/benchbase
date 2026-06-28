"""Inject BenchBase thinking/output split metrics into llama-benchy JSON reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from llama_benchy.client import RequestResult
from llama_benchy.results import BenchmarkResults

from benchbase.runners.llama_benchy_stream import throughput_from_timestamps


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
    """Summarize reasoning-stream throughput and latency across benchmark batches."""
    think_speeds: list[float] = []
    think_ttfts_ms: list[float] = []
    think_durations_ms: list[float] = []
    think_token_counts: list[float] = []
    output_ttfts_ms: list[float] = []

    for batch in run_results:
        for res in batch:
            if not res or res.error:
                continue

            reasoning_ts = getattr(res, "reasoning_token_timestamps", None) or []
            first_reasoning = getattr(res, "first_reasoning_token_ts", None)
            if first_reasoning is not None:
                think_ttfts_ms.append((first_reasoning - res.start_ts) * 1000)

            think_tps, _, think_duration = throughput_from_timestamps(
                reasoning_ts,
                start_ts=res.start_ts,
                first_ts=first_reasoning,
            )
            if think_tps is not None:
                think_speeds.append(think_tps)
            if think_duration is not None:
                think_durations_ms.append(think_duration * 1000)
            reasoning_total = getattr(res, "reasoning_total_tokens", 0)
            if reasoning_total:
                think_token_counts.append(float(reasoning_total))

            if res.first_token_ts is not None:
                output_ttfts_ms.append((res.first_token_ts - res.start_ts) * 1000)

    return {
        "think_tg_throughput": _metric(think_speeds),
        "think_ttft_ms": _metric(think_ttfts_ms),
        "think_duration_ms": _metric(think_durations_ms),
        "think_token_count": _metric(think_token_counts),
        "output_ttft_ms": _metric(output_ttfts_ms),
    }


def _has_thinking_data(thinking: dict[str, dict[str, Any] | None]) -> bool:
    return any(thinking.get(key) for key in thinking)


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
            if _has_thinking_data(thinking):
                benchmark["benchbase_thinking"] = thinking
            output_ttft = thinking.get("output_ttft_ms")
            if output_ttft and not benchmark.get("e2e_ttft"):
                benchmark["output_ttft_ms"] = output_ttft

        report_path.write_text(json.dumps(data, indent=2))

    BenchmarkResults.__init__ = init_patched
    BenchmarkResults.add = add_patched
    BenchmarkResults.save_report = save_report_patched
    BenchmarkResults._benchbase_results_patch_applied = True
