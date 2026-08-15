"""Relative-rank scoring across v2 quality axes (speed excluded from Borda)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.config import load_settings
from benchbase.controls import get_scorer_status_map, is_control_model_name
from benchbase.db.models import BenchmarkSuite, Model, ModelStatus, Result, Run, RunStatus
from benchbase.work_clock import (
    EMPTY_CLOCK,
    WORK_CLOCK_AXES,
    attach_speed_indexes,
    compute_work_clocks_by_model,
    load_grouped_runs,
    pick_sitting,
    sittings_from_runs,
    successes_from_metrics,
)

QUALITY_AXES = [
    "knowledge",
    "reasoning",
    "math",
    "coding",
    "tool_calling",
    "instruction",
    "structured",
    "long_context",
]

AXIS_CONFIG: dict[str, dict[str, Any]] = {
    axis: {
        "primary_prefix": f"{axis}:",
        "unit": "%",
        "higher_is_better": True,
    }
    for axis in QUALITY_AXES
}

SPEED_PRIMARY_PREFIX = "speed:output_tps"
SPEED_TTFT_PREFIX = "speed:ttft_ms"
SPEED_PREFILL_PREFIX = "speed:prefill_tps"
SPEED_THINK_PREFIX = "speed:think_ms"

N_CORRECT_IDENTITY_REASON = "n_correct does not match sitting axis successes"


async def _current_suite_versions(db: AsyncSession) -> dict[str, str]:
    suites = (await db.execute(select(BenchmarkSuite))).scalars().all()
    return {s.axis.value: s.suite_version for s in suites}


async def _work_clocks_with_index(db: AsyncSession) -> dict[str, dict[str, Any]]:
    clocks = await compute_work_clocks_by_model(db)
    attach_speed_indexes(clocks, load_settings().work_clock_reference_model)
    return clocks


async def compute_scorecard(
    run_ids: list[int], db: AsyncSession
) -> list[dict[str, Any]]:
    current_versions = await _current_suite_versions(db)
    scorer_status = await get_scorer_status_map(db)
    models_data: dict[str, dict[str, Any]] = {}

    for run_id in run_ids:
        run = await db.get(
            Run, run_id,
            options=[selectinload(Run.model), selectinload(Run.suite)],
        )
        if not run or not run.model:
            continue
        if is_control_model_name(run.model.name):
            continue

        stmt = select(Result).where(Result.run_id == run_id)
        rows = await db.execute(stmt)
        results = rows.scalars().all()

        name = run.model.name
        if name not in models_data:
            models_data[name] = {
                "model_name": name,
                "model_color": run.model.color,
                "base_model": run.model.base_model,
                "quant_rank": run.model.quant_rank,
                "status": run.model.status.value if run.model.status else None,
                "context_window": run.model.context_window,
                "vram_gb": run.model.vram_gb,
                "suite_versions": {},
                "all_results": [],
                "axis_runs": {},
                "work_clock_group": None,
            }
        if run.suite:
            axis = run.suite.axis.value
            models_data[name]["suite_versions"][axis] = run.suite.suite_version
            if run.suite.suite_version == current_versions.get(axis):
                models_data[name]["axis_runs"].setdefault(axis, [])
                models_data[name]["axis_runs"][axis].extend(results)
        models_data[name]["all_results"].extend(results)

    work_clocks = await _work_clocks_with_index(db)
    return _build_scorecards(
        models_data, current_versions, scorer_status, work_clocks=work_clocks
    )


async def compute_model_scorecard(db: AsyncSession) -> list[dict[str, Any]]:
    """Scorecard from one sitting per model (pick_sitting) for axes + work clock."""
    current_versions = await _current_suite_versions(db)
    scorer_status = await get_scorer_status_map(db)

    incomplete_groups: set[str] = set()
    all_grouped = await db.execute(
        select(Run).where(Run.run_group_id.is_not(None))
    )
    by_group: dict[str, list[Run]] = {}
    for r in all_grouped.scalars().all():
        if r.run_group_id:
            by_group.setdefault(r.run_group_id, []).append(r)
    for gid, members in by_group.items():
        if not all(m.status == RunStatus.COMPLETED for m in members):
            incomplete_groups.add(gid)

    grouped_runs = await load_grouped_runs(db)
    sittings = sittings_from_runs(grouped_runs)
    sittings_by_model: dict[str, list] = {}
    for sitting in sittings:
        if sitting.model_name:
            sittings_by_model.setdefault(sitting.model_name, []).append(sitting)

    group_runs: dict[str, list[Run]] = {}
    for run in grouped_runs:
        if run.run_group_id:
            group_runs.setdefault(run.run_group_id, []).append(run)

    models_result = await db.execute(select(Model).order_by(Model.name))
    all_models = models_result.scalars().all()
    included = [
        m for m in all_models
        if not is_control_model_name(m.name)
        and m.status != ModelStatus.ARCHIVED
    ]

    models_data: dict[str, dict[str, Any]] = {}
    for model in included:
        runs_result = await db.execute(
            select(Run)
            .where(Run.model_id == model.id, Run.status == RunStatus.COMPLETED)
            .options(selectinload(Run.results), selectinload(Run.suite))
            .order_by(Run.id.desc())
        )
        runs = runs_result.scalars().all()
        all_results: list[Result] = []
        suite_versions: dict[str, str] = {}
        axis_runs: dict[str, list[Result]] = {}
        best_tier: str | None = None
        work_clock_group: str | None = None

        sitting = pick_sitting(sittings_by_model.get(model.name, []))
        if (
            sitting is not None
            and sitting.run_group_id not in incomplete_groups
        ):
            work_clock_group = sitting.run_group_id
            best_tier = sitting.tier
            for run in group_runs.get(sitting.run_group_id, []):
                if run.status != RunStatus.COMPLETED or not run.suite:
                    continue
                axis = run.suite.axis.value
                if axis not in QUALITY_AXES:
                    continue
                suite_versions[axis] = run.suite.suite_version
                all_results.extend(run.results or [])
                if run.suite.suite_version == current_versions.get(axis):
                    axis_runs[axis] = list(run.results or [])

        # Speed plate tok/s: latest completed Speed run at current suite version.
        for run in runs:
            if not run.suite or run.suite.axis.value != "speed":
                continue
            suite_versions["speed"] = run.suite.suite_version
            if run.suite.suite_version == current_versions.get("speed"):
                axis_runs["speed"] = list(run.results or [])
                all_results.extend(run.results or [])
            break

        # History flag: any completed quality/speed work, not only the sitting.
        has_history = bool(runs)

        models_data[model.name] = {
            "model_name": model.name,
            "model_color": model.color,
            "base_model": model.base_model,
            "quant_rank": model.quant_rank,
            "status": model.status.value if model.status else None,
            "is_active": model.status == ModelStatus.ACTIVE,
            "has_benchmark_history": has_history,
            "best_tier": best_tier,
            "context_window": model.context_window,
            "vram_gb": model.vram_gb,
            "suite_versions": suite_versions,
            "all_results": all_results,
            "axis_runs": axis_runs,
            "work_clock_group": work_clock_group,
        }

    work_clocks = await _work_clocks_with_index(db)
    return _build_scorecards(
        models_data, current_versions, scorer_status, work_clocks=work_clocks
    )


def _assign_ranks(
    scored: list[tuple[str, float]],
    *,
    higher_is_better: bool,
) -> dict[str, dict[str, Any]]:
    valid = list(scored)
    valid.sort(key=lambda x: x[1], reverse=higher_is_better)
    if not valid:
        return {}

    rank_by_name: dict[str, int] = {}
    for i, (name, score) in enumerate(valid):
        if i > 0 and score == valid[i - 1][1]:
            rank_by_name[name] = rank_by_name[valid[i - 1][0]]
        else:
            rank_by_name[name] = i + 1

    rank_counts: dict[int, int] = {}
    for rank in rank_by_name.values():
        rank_counts[rank] = rank_counts.get(rank, 0) + 1

    return {
        name: {
            "rank": rank_by_name[name],
            "rank_tied": rank_counts[rank_by_name[name]] > 1,
        }
        for name in rank_by_name
    }


def _borda_points(rank: int, competitors: int) -> int:
    return competitors - rank


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _axis_successes_total(axis_runs: dict[str, list[Result]]) -> int:
    total = 0
    for axis in WORK_CLOCK_AXES:
        for r in axis_runs.get(axis) or []:
            total += successes_from_metrics(r.metrics_json)
    return total


def _reconcile_work_clock(
    clock: dict[str, Any],
    axis_runs: dict[str, list[Result]],
    *,
    expected_group: str | None,
) -> dict[str, Any]:
    """Null the clock when it does not match the sitting's axis successes."""
    out = dict(clock)
    if expected_group and out.get("work_clock_group") not in (None, expected_group):
        out["sec_per_correct"] = None
        out["n_correct"] = None
        out["invalid_reason"] = N_CORRECT_IDENTITY_REASON
        out["work_clock_index"] = None
        return out
    axis_sum = _axis_successes_total(axis_runs)
    n_correct = out.get("n_correct")
    if (
        n_correct is not None
        and isinstance(n_correct, (int, float))
        and int(n_correct) != axis_sum
        and axis_runs
    ):
        out["sec_per_correct"] = None
        out["invalid_reason"] = N_CORRECT_IDENTITY_REASON
        out["work_clock_index"] = None
        # Keep reported n_correct as the axis sum for identity with the radar.
        out["n_correct"] = axis_sum
    return out


def _build_scorecards(
    models_data: dict[str, dict[str, Any]],
    current_versions: dict[str, str],
    scorer_status: dict[str, str],
    work_clocks: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    scorecards = []
    for model_name, mdata in models_data.items():
        dimensions: dict[str, dict[str, Any]] = {}
        for dim, cfg in AXIS_CONFIG.items():
            status = scorer_status.get(dim, "unknown")
            version_ok = (mdata.get("suite_versions") or {}).get(dim) == current_versions.get(dim)
            invalid = status == "invalid"
            mismatched = not version_ok and (mdata.get("suite_versions") or {}).get(dim) is not None

            results_for_axis = (mdata.get("axis_runs") or {}).get(dim) or []
            if invalid or mismatched or not results_for_axis:
                primary, details, sample_count, ci_low, ci_high, n_items, planned_n = (
                    None, {}, 0, None, None, None, None
                )
            else:
                primary, details, sample_count, ci_low, ci_high, n_items, planned_n = (
                    _extract_axis(results_for_axis, cfg)
                )

            incomplete = (
                planned_n is not None
                and n_items is not None
                and int(n_items) != int(planned_n)
            )
            dimensions[dim] = {
                "primary": primary,
                "unit": cfg["unit"],
                "details": details,
                "sample_count": sample_count,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "n_items": n_items,
                "planned_n": planned_n,
                "suite_version": (mdata.get("suite_versions") or {}).get(dim),
                "current_suite_version": current_versions.get(dim),
                "scorer_status": status,
                "version_mismatch": mismatched,
                "excluded_from_ranking": (
                    invalid or mismatched or primary is None or incomplete
                ),
            }

        speed_results = (mdata.get("axis_runs") or {}).get("speed") or mdata["all_results"]
        clock = (work_clocks or {}).get(model_name) or dict(EMPTY_CLOCK)
        clock = _reconcile_work_clock(
            clock,
            mdata.get("axis_runs") or {},
            expected_group=mdata.get("work_clock_group"),
        )
        speed = _extract_speed(speed_results, work_clock=clock)
        scorecards.append({
            "model_name": model_name,
            "model_color": mdata.get("model_color"),
            "base_model": mdata.get("base_model"),
            "quant_rank": mdata.get("quant_rank"),
            "status": mdata.get("status"),
            "is_active": mdata.get("is_active"),
            "has_benchmark_history": mdata.get("has_benchmark_history"),
            "best_tier": mdata.get("best_tier"),
            "context_window": mdata.get("context_window"),
            "vram_gb": mdata.get("vram_gb"),
            "work_clock_group": mdata.get("work_clock_group") or speed.get("work_clock_group"),
            "dimensions": dimensions,
            "speed": speed,
            "scorer_status": scorer_status,
        })

    for dim, cfg in AXIS_CONFIG.items():
        scores = [
            (sc["model_name"], sc["dimensions"][dim]["primary"])
            for sc in scorecards
            if not sc["dimensions"][dim].get("excluded_from_ranking")
        ]
        valid_scores = [(name, s) for name, s in scores if s is not None]
        competitors = len(valid_scores)
        rank_info = _assign_ranks(valid_scores, higher_is_better=cfg["higher_is_better"])

        for sc in scorecards:
            info = rank_info.get(sc["model_name"])
            rank = info["rank"] if info else None
            sc["dimensions"][dim]["rank"] = rank
            sc["dimensions"][dim]["rank_tied"] = info["rank_tied"] if info else False
            sc["dimensions"][dim]["competitors"] = competitors if rank is not None else 0
            sc["dimensions"][dim]["borda_points"] = (
                _borda_points(rank, competitors) if rank is not None else 0
            )

    for sc in scorecards:
        sc["borda_score"] = sum(
            sc["dimensions"][d]["borda_points"] for d in QUALITY_AXES
        )

    borda_scored = [
        (sc["model_name"], sc["borda_score"])
        for sc in scorecards
        if sc["borda_score"] > 0
    ]
    overall_rank_info = _assign_ranks(borda_scored, higher_is_better=True)
    for sc in scorecards:
        info = overall_rank_info.get(sc["model_name"])
        sc["overall_rank"] = info["rank"] if info else None
        sc["overall_rank_tied"] = info["rank_tied"] if info else False
        sc["overall_competitors"] = len(borda_scored)

    scorecards.sort(
        key=lambda x: (
            x.get("overall_rank") or 999,
            -x.get("borda_score", 0),
        )
    )
    return scorecards


def _extract_axis(
    results: list[Result], cfg: dict[str, Any]
) -> tuple[
    float | None,
    dict[str, Any],
    int,
    float | None,
    float | None,
    int | None,
    int | None,
]:
    primary_scores: list[float] = []
    details: dict[str, Any] = {}
    ci_lows: list[float] = []
    ci_highs: list[float] = []
    n_items_vals: list[int] = []
    planned_vals: list[int] = []

    for r in results:
        if not r.task_name.startswith(cfg["primary_prefix"]):
            continue
        if r.score is not None:
            primary_scores.append(r.score)
            details[r.task_name] = r.score
        if r.ci_low is not None:
            ci_lows.append(r.ci_low)
        if r.ci_high is not None:
            ci_highs.append(r.ci_high)
        if r.n_items is not None:
            n_items_vals.append(r.n_items)
        if r.metrics_json:
            try:
                m = json.loads(r.metrics_json)
            except json.JSONDecodeError:
                m = {}
            if isinstance(m, dict):
                pn = m.get("planned_n")
                if isinstance(pn, (int, float)) and not isinstance(pn, bool):
                    planned_vals.append(int(pn))
                elif r.n_items is not None:
                    # Legacy rows without planned_n: treat scored n as planned.
                    planned_vals.append(int(r.n_items))

    primary = _avg(primary_scores)
    ci_low = _avg(ci_lows)
    ci_high = _avg(ci_highs)
    n_items = int(round(sum(n_items_vals) / len(n_items_vals))) if n_items_vals else None
    planned_n = int(round(sum(planned_vals) / len(planned_vals))) if planned_vals else None
    if primary is not None and (ci_low is None or ci_high is None) and n_items:
        from benchbase.stats import wilson_interval
        successes = int(round(primary / 100.0 * n_items))
        ci_low, ci_high = wilson_interval(successes, n_items)
    return primary, details, len(primary_scores), ci_low, ci_high, n_items, planned_n


def _extract_speed(
    results: list[Result],
    work_clock: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_tps: list[float] = []
    ttft: list[float] = []
    prefill: list[float] = []
    think_ms: list[float] = []
    think_tokens: list[float] = []
    for r in results:
        if r.score is None:
            continue
        if r.task_name.startswith(SPEED_PRIMARY_PREFIX) or r.task_name.startswith("speed:output_tg"):
            output_tps.append(r.score)
        elif r.task_name.startswith(SPEED_TTFT_PREFIX) or r.task_name.startswith("speed:output_ttft"):
            ttft.append(r.score)
        elif r.task_name.startswith(SPEED_PREFILL_PREFIX) or r.task_name.startswith("speed:pp"):
            prefill.append(r.score)
        elif r.task_name.startswith(SPEED_THINK_PREFIX) or r.task_name.startswith("speed:think_time"):
            think_ms.append(r.score)
            if r.metrics_json:
                try:
                    m = json.loads(r.metrics_json)
                    tok = m.get("think_tokens")
                    if isinstance(tok, dict) and tok.get("mean") is not None:
                        think_tokens.append(float(tok["mean"]))
                    elif isinstance(tok, (int, float)):
                        think_tokens.append(float(tok))
                except json.JSONDecodeError:
                    pass

    clock = work_clock or dict(EMPTY_CLOCK)
    return {
        "output_tps": _avg(output_tps),
        "ttft_ms": _avg(ttft),
        "prefill_tps": _avg(prefill),
        "think_ms": _avg(think_ms),
        "think_tokens": _avg(think_tokens),
        "unit_tps": "tok/s",
        "unit_ms": "ms",
        "sec_per_correct": clock.get("sec_per_correct"),
        "suite_wall_s": clock.get("suite_wall_s"),
        "n_correct": clock.get("n_correct"),
        "work_clock_tier": clock.get("work_clock_tier"),
        "invalid_reason": clock.get("invalid_reason"),
        "work_clock_group": clock.get("work_clock_group"),
        "work_clock_index": clock.get("work_clock_index"),
        "work_clock_reference": clock.get("work_clock_reference"),
        "work_clock_reference_sec": clock.get("work_clock_reference_sec"),
    }
