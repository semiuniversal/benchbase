"""Relative-rank scoring across v2 quality axes (speed excluded from Borda)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.controls import get_scorer_status_map, is_control_model_name
from benchbase.db.models import BenchmarkSuite, Model, ModelStatus, Result, Run, RunStatus

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


async def _current_suite_versions(db: AsyncSession) -> dict[str, str]:
    suites = (await db.execute(select(BenchmarkSuite))).scalars().all()
    return {s.axis.value: s.suite_version for s in suites}


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
                "suite_versions": {},
                "all_results": [],
                "axis_runs": {},
            }
        if run.suite:
            axis = run.suite.axis.value
            models_data[name]["suite_versions"][axis] = run.suite.suite_version
            # Prefer latest completed run per axis at current suite version.
            if run.suite.suite_version == current_versions.get(axis):
                models_data[name]["axis_runs"].setdefault(axis, [])
                models_data[name]["axis_runs"][axis].extend(results)
        models_data[name]["all_results"].extend(results)

    return _build_scorecards(models_data, current_versions, scorer_status)


async def compute_model_scorecard(db: AsyncSession) -> list[dict[str, Any]]:
    current_versions = await _current_suite_versions(db)
    scorer_status = await get_scorer_status_map(db)

    # Groups that are not fully completed must not contribute axis scores.
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

    models_result = await db.execute(select(Model).order_by(Model.name))
    all_models = models_result.scalars().all()
    # Archived models keep their runs in the DB but are omitted from Compare.
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
        seen_axis: set[str] = set()
        for run in runs:
            if run.run_group_id and run.run_group_id in incomplete_groups:
                continue
            all_results.extend(run.results)
            if not run.suite:
                continue
            axis = run.suite.axis.value
            suite_versions[axis] = run.suite.suite_version
            # Latest run only, and only if suite version matches current catalog.
            if axis in seen_axis:
                continue
            seen_axis.add(axis)
            if run.suite.suite_version == current_versions.get(axis):
                axis_runs[axis] = list(run.results)
        models_data[model.name] = {
            "model_name": model.name,
            "model_color": model.color,
            "base_model": model.base_model,
            "quant_rank": model.quant_rank,
            "status": model.status.value if model.status else None,
            "is_active": model.status == ModelStatus.ACTIVE,
            "has_benchmark_history": len(all_results) > 0 or len(axis_runs) > 0,
            "suite_versions": suite_versions,
            "all_results": all_results,
            "axis_runs": axis_runs,
        }

    return _build_scorecards(models_data, current_versions, scorer_status)


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


def _build_scorecards(
    models_data: dict[str, dict[str, Any]],
    current_versions: dict[str, str],
    scorer_status: dict[str, str],
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
                primary, details, sample_count, ci_low, ci_high, n_items = (
                    None, {}, 0, None, None, None
                )
            else:
                primary, details, sample_count, ci_low, ci_high, n_items = _extract_axis(
                    results_for_axis, cfg
                )

            dimensions[dim] = {
                "primary": primary,
                "unit": cfg["unit"],
                "details": details,
                "sample_count": sample_count,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "n_items": n_items,
                "suite_version": (mdata.get("suite_versions") or {}).get(dim),
                "current_suite_version": current_versions.get(dim),
                "scorer_status": status,
                "version_mismatch": mismatched,
                "excluded_from_ranking": invalid or mismatched or primary is None,
            }

        # Latest completed Speed run at the current suite version (same rule as quality axes).
        # Averaging historical cells would mix repaired exact-tg probes with short-EOS junk.
        speed_results = (mdata.get("axis_runs") or {}).get("speed") or mdata["all_results"]
        speed = _extract_speed(speed_results)
        scorecards.append({
            "model_name": model_name,
            "model_color": mdata.get("model_color"),
            "base_model": mdata.get("base_model"),
            "quant_rank": mdata.get("quant_rank"),
            "status": mdata.get("status"),
            "is_active": mdata.get("is_active"),
            "has_benchmark_history": mdata.get("has_benchmark_history"),
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
) -> tuple[float | None, dict[str, Any], int, float | None, float | None, int | None]:
    primary_scores: list[float] = []
    details: dict[str, Any] = {}
    ci_lows: list[float] = []
    ci_highs: list[float] = []
    n_items_vals: list[int] = []

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

    primary = _avg(primary_scores)
    ci_low = _avg(ci_lows)
    ci_high = _avg(ci_highs)
    n_items = int(round(sum(n_items_vals) / len(n_items_vals))) if n_items_vals else None
    if primary is not None and (ci_low is None or ci_high is None) and n_items:
        from benchbase.stats import wilson_interval
        successes = int(round(primary / 100.0 * n_items))
        ci_low, ci_high = wilson_interval(successes, n_items)
    return primary, details, len(primary_scores), ci_low, ci_high, n_items


def _extract_speed(results: list[Result]) -> dict[str, Any]:
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

    return {
        "output_tps": _avg(output_tps),
        "ttft_ms": _avg(ttft),
        "prefill_tps": _avg(prefill),
        "think_ms": _avg(think_ms),
        "think_tokens": _avg(think_tokens),
        "unit_tps": "tok/s",
        "unit_ms": "ms",
    }
