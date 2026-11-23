"""Speed benchmark runner backed by llama-benchy."""

from __future__ import annotations

import json
import shutil
import sys
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import inference_openai_v1_root, load_settings
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.llama_benchy_corpus_patch import default_corpus_source
from benchbase.runners.registry import register_runner
from benchbase.runners.run_metadata import metadata_int
from benchbase.runners.subprocess_utils import make_temp_dir, run_tool
from benchbase.run_log import RunLogManager
from benchbase.decode_tps import (
    HEADLINE_METHOD,
    PROFILE_ID,
    PROFILE_ID_32K,
    PROFILE_MEASURED_REPS,
    PROFILE_PP,
    PROFILE_PP_32K,
    PROFILE_REVISION,
    PROFILE_TG,
    VISIBLE_METHOD,
    median_decode_headline,
    profile_qualifier,
)
from benchbase.runners.run_metadata import parse_run_metadata
from benchbase.speed_gate import (
    DECODE_TPS_PREFIX,
    VISIBLE_DECODE_PREFIX,
    annotate_invalid_metrics,
    gate_decode_replicates,
    metric_mean,
    prefill_invalid_reason,
)


@register_runner("speed")
class SpeedRunner(BenchmarkRunner):
    """Invokes llama-benchy to measure latency, TTFT, and generation throughput."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        settings = load_settings()
        model_name = run.model.name
        base_url = inference_openai_v1_root(settings.litellm_base_url)
        tmpdir = make_temp_dir("benchbase_speed_")
        result_file = tmpdir / "results.json"

        suite_config = json.loads(run.suite.config_json) if run.suite.config_json else {}
        pp = suite_config.get("pp", [128])
        tg = suite_config.get("tg", [2048])
        runs_count = _speed_runs_count(run, suite_config)

        args = [
            sys.executable, "-m", "benchbase.runners.llama_benchy_runner",
            "--base-url", base_url,
            "--model", model_name,
            "--tokenizer", suite_config.get("tokenizer", "gpt2"),
            "--format", "json",
            "--save-result", str(result_file),
            "--latency-mode", "generation",
            "--runs", str(runs_count),
            "--exact-tg",
            "--no-adapt-prompt",
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
                task_name = f"speed:prefill_tps{bm.get('prompt_size', '')}{suffix}"
                metrics = {
                    "type": "prefill_tps",
                    "throughput_mean": pp_metric["mean"],
                    "throughput_std": pp_metric["std"],
                    "ttfr": _extract(bm, "ttfr"),
                    "est_ppt": _extract(bm, "est_ppt"),
                    "e2e_ttft": _extract(bm, "e2e_ttft"),
                }
                score = pp_metric["mean"]
                reason = prefill_invalid_reason(
                    metric_mean(pp_metric),
                    metric_mean(bm.get("est_ppt")),
                    bm.get("prompt_size"),
                )
                if reason:
                    metrics_json = annotate_invalid_metrics(metrics, score, reason)
                    score = None
                    _log_speed_gate(run.id, task_name, reason)
                else:
                    metrics_json = json.dumps(metrics)
                db.add(Result(
                    run_id=run.id,
                    task_name=task_name,
                    score=score,
                    metrics_json=metrics_json,
                    raw_output_json=json.dumps(bm),
                ))

            prompt_size = bm.get("prompt_size") or (suite_config.get("pp") or [PROFILE_PP])[0]
            profile_map = suite_config.get("profile_by_pp") or {}
            active_profile = profile_map.get(int(prompt_size)) or suite_config.get("profile_id")
            response_size = bm.get("response_size")
            is_v1_profile = (
                active_profile in (PROFILE_ID, PROFILE_ID_32K)
                and response_size == PROFILE_TG
            )

            generated = thinking.get("generated_decode_tg_throughput") or bm.get(
                "generated_decode_tg_throughput"
            )
            if is_v1_profile and generated and generated.get("values"):
                gen_tokens = thinking.get("generated_token_count") or bm.get(
                    "generated_token_count"
                )
                score, reason, valid_n, total_n = median_decode_headline(
                    gen_tokens, generated, tg=float(PROFILE_TG)
                )
                task_name = f"{DECODE_TPS_PREFIX}{response_size}{suffix}"
                metrics = {
                    "type": "decode_tps",
                    "metric": "decode_tps",
                    "profile_id": active_profile or PROFILE_ID,
                    "profile_revision": PROFILE_REVISION,
                    "method": HEADLINE_METHOD,
                    "source": "llama-benchy",
                    "target_tg": PROFILE_TG,
                    "target_pp": int(prompt_size),
                    "throughput_median": score,
                    "throughput_mean": generated.get("mean"),
                    "throughput_std": generated.get("std"),
                    "generated_token_count": gen_tokens,
                    "repetitions_requested": PROFILE_MEASURED_REPS,
                    "repetitions_valid": valid_n,
                    "repetitions_total": total_n,
                    "aggregation": "median",
                    "qualifier": profile_qualifier(active_profile or PROFILE_ID),
                    "ttft_ms": _resolve_ttft(thinking, bm),
                    "think_time_ms": _resolve_think_time(thinking),
                    "visible_decode_tps": _metric_mean(
                        thinking.get("output_decode_tg_throughput")
                        or bm.get("output_decode_tg_throughput")
                    ),
                }
                if reason:
                    metrics_json = annotate_invalid_metrics(metrics, score, reason)
                    score = None
                    _log_speed_gate(run.id, task_name, reason)
                else:
                    metrics_json = json.dumps(metrics)
                db.add(Result(
                    run_id=run.id,
                    task_name=task_name,
                    score=score,
                    metrics_json=metrics_json,
                    raw_output_json=json.dumps(bm),
                ))

            # Visible-only decode (labeled; legacy output_tps alias when not v1 profile).
            output_tps = (
                thinking.get("output_decode_tg_throughput")
                or bm.get("output_decode_tg_throughput")
                or thinking.get("output_tg_throughput")
                or bm.get("output_tg_throughput")
            )
            if output_tps and output_tps.get("mean") is not None:
                visible_prefix = (
                    VISIBLE_DECODE_PREFIX if is_v1_profile else "speed:output_tps"
                )
                task_name = f"{visible_prefix}{response_size}{suffix}"
                metrics = {
                    "type": "visible_decode_tps" if is_v1_profile else "output_tps",
                    "method": VISIBLE_METHOD if is_v1_profile else "legacy_visible_output",
                    "throughput_mean": output_tps["mean"],
                    "throughput_std": output_tps.get("std"),
                    "ttft_ms": _resolve_ttft(thinking, bm),
                    "think_time_ms": _resolve_think_time(thinking),
                    "think_tokens": thinking.get("think_token_count"),
                    "output_token_count": thinking.get("output_token_count"),
                    "total_ms": thinking.get("output_completion_ms"),
                }
                if is_v1_profile:
                    metrics["profile_id"] = active_profile or PROFILE_ID
                score = output_tps["mean"]
                gate_tg = PROFILE_TG if is_v1_profile else bm.get("response_size")
                gated, reason = gate_decode_replicates(
                    thinking.get("output_token_count") or bm.get("output_token_count"),
                    output_tps,
                    gate_tg,
                )
                if reason:
                    metrics_json = annotate_invalid_metrics(metrics, score, reason)
                    score = None
                    if not is_v1_profile:
                        _log_speed_gate(run.id, task_name, reason)
                else:
                    if gated is not None:
                        score = gated
                        metrics["throughput_mean"] = gated
                    metrics_json = json.dumps(metrics)
                db.add(Result(
                    run_id=run.id,
                    task_name=task_name,
                    score=score,
                    metrics_json=metrics_json,
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
                "Note: model produced no visible output tokens — output_tps unavailable. "
                "Think-phase and total wall time are still recorded when present.",
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
                "decode_tps (headline): generated tokens after first token, profile "
                "decode-4k-512-c1-v1. Visible decode kept separately; legacy output_tps "
                "rows unchanged for older profiles."
            ),
        }


def _speed_runs_count(run: Run, suite_config: dict[str, Any]) -> int:
    meta = parse_run_metadata(run)
    if meta.get("runs") is not None:
        return int(meta["runs"])
    if suite_config.get("runs") is not None:
        return int(suite_config["runs"])
    passes = suite_config.get("passes") or {}
    tier = run.tier.value if getattr(run, "tier", None) else "standard"
    return int(passes.get(tier, PROFILE_MEASURED_REPS))


def _log_speed_gate(run_id: int, task_name: str, reason: str) -> None:
    RunLogManager.log(
        run_id,
        f"Speed gate: discarded numeric {task_name} ({reason}). "
        "TTFT/token-count still stored. Re-run Speed after the exact-tg fix for a comparable tok/s.",
    )


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


def _metric_mean(metric: Any) -> float | None:
    if isinstance(metric, dict) and metric.get("mean") is not None:
        try:
            return float(metric["mean"])
        except (TypeError, ValueError):
            return None
    return None


def _resolve_ttft(
    thinking: dict[str, Any], bm: dict[str, Any]
) -> dict[str, Any] | None:
    """Time to first token — prefer first reasoning token, never think wall."""
    for candidate in (
        thinking.get("think_ttft_ms"),
        thinking.get("output_ttft_ms"),
        bm.get("output_ttft_ms"),
        bm.get("e2e_ttft"),
        thinking.get("ttft_ms"),
    ):
        if _metric_mean(candidate) is not None:
            return candidate
    return None


def _resolve_think_time(thinking: dict[str, Any]) -> dict[str, Any] | None:
    """Thinking-phase duration; do not reuse TTFT / wall-to-first-visible."""
    duration = thinking.get("think_duration_ms")
    if _metric_mean(duration) is not None:
        return duration
    # Legacy think_time_ms often equals output_ttft (wall to first visible).
    # Only keep it when it clearly differs from TTFT-like measures.
    think_wall = thinking.get("think_time_ms")
    tw = _metric_mean(think_wall)
    if tw is None:
        return None
    ttft_like = (
        _metric_mean(thinking.get("think_ttft_ms"))
        or _metric_mean(thinking.get("output_ttft_ms"))
    )
    if ttft_like is not None and abs(tw - ttft_like) < 1.0:
        return None
    return think_wall


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
    has_visible = bool(
        thinking.get("output_tg_throughput")
        or thinking.get("output_token_count")
        or thinking.get("output_ttft_ms")
    )
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
                "no_visible_output": not has_visible,
            }),
            raw_output_json=json.dumps(thinking),
        ))

    # TTFT: time to first token (reasoning first when present). Never alias think wall.
    ttft = _resolve_ttft(thinking, bm)
    if ttft and ttft.get("mean") is not None:
        db.add(Result(
            run_id=run_id,
            task_name=f"speed:ttft_ms{response_size}{suffix}",
            score=ttft["mean"],
            metrics_json=json.dumps({
                "type": "ttft_ms",
                "unit": "ms",
                "mean": ttft["mean"],
                "std": ttft.get("std"),
            }),
            raw_output_json=json.dumps(thinking or {"ttft_ms": ttft}),
        ))

    think_time = _resolve_think_time(thinking)
    if think_time and think_time.get("mean") is not None:
        db.add(Result(
            run_id=run_id,
            task_name=f"speed:think_ms{response_size}{suffix}",
            score=think_time["mean"],
            metrics_json=json.dumps({
                "type": "think_ms",
                "unit": "ms",
                "mean": think_time["mean"],
                "std": think_time.get("std"),
                "think_tokens": thinking.get("think_token_count"),
            }),
            raw_output_json=json.dumps(thinking),
        ))

    if completion and completion.get("mean") is not None:
        db.add(Result(
            run_id=run_id,
            task_name=f"speed:total_ms{response_size}{suffix}",
            score=completion["mean"],
            metrics_json=json.dumps({
                "type": "total_ms",
                "unit": "ms",
                "mean": completion["mean"],
                "std": completion.get("std"),
            }),
            raw_output_json=json.dumps(thinking),
        ))

    token_count = thinking.get("output_token_count")
    if token_count and token_count.get("mean") is not None:
        db.add(Result(
            run_id=run_id,
            task_name=f"speed:output_token_count{response_size}{suffix}",
            score=token_count["mean"],
            metrics_json=json.dumps({
                "type": "output_token_count",
                "unit": "tokens",
                "mean": token_count["mean"],
                "std": token_count.get("std"),
            }),
            raw_output_json=json.dumps(thinking),
        ))


def _extract(bm: dict, key: str) -> dict | None:
    val = bm.get(key)
    if val is None:
        return None
    return {"mean": val["mean"], "std": val["std"]}
