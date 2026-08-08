"""Relative-rank scoring across v2 quality axes (speed excluded from Borda)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Model, ModelStatus, Result, Run, RunStatus

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


async def compute_scorecard(
    run_ids: list[int], db: AsyncSession
) -> list[dict[str, Any]]:
    models_data: dict[str, dict[str, Any]] = {}

    for run_id in run_ids:
        run = await db.get(
            Run, run_id,
            options=[selectinload(Run.model), selectinload(Run.suite)],
        )
        if not run or not run.model:
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
            }
        if run.suite:
            models_data[name]["suite_versions"][run.suite.axis.value] = run.suite.suite_version
        models_data[name]["all_results"].extend(results)

    return _build_scorecards(models_data)


async def compute_model_scorecard(db: AsyncSession) -> list[dict[str, Any]]:
    completed_ids_result = await db.execute(
        select(Run.model_id).where(Run.status == RunStatus.COMPLETED).distinct()
    )
    completed_model_ids = {row[0] for row in completed_ids_result.all()}

    models_result = await db.execute(select(Model).order_by(Model.name))
    all_models = models_result.scalars().all()
    included = [
        m for m in all_models
        if m.status != ModelStatus.ARCHIVED or m.id in completed_model_ids
    ]

    models_data: dict[str, dict[str, Any]] = {}
    for model in included:
        runs_result = await db.execute(
            select(Run)
            .where(Run.model_id == model.id, Run.status == RunStatus.COMPLETED)
            .options(selectinload(Run.results), selectinload(Run.suite))
        )
        runs = runs_result.scalars().all()
        all_results: list[Result] = []
        suite_versions: dict[str, str] = {}
        for run in runs:
            all_results.extend(run.results)
            if run.suite:
                suite_versions[run.suite.axis.value] = run.suite.suite_version
        models_data[model.name] = {
            "model_name": model.name,
            "model_color": model.color,
            "base_model": model.base_model,
            "quant_rank": model.quant_rank,
            "status": model.status.value if model.status else None,
            "is_active": model.status == ModelStatus.ACTIVE,
            "has_benchmark_history": len(runs) > 0,
            "suite_versions": suite_versions,
            "all_results": all_results,
        }

    return _build_scorecards(models_data)


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


def _build_scorecards(models_data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    scorecards = []
    for model_name, mdata in models_data.items():
        dimensions: dict[str, dict[str, Any]] = {}
        for dim, cfg in AXIS_CONFIG.items():
            primary, details, sample_count, ci_low, ci_high, n_items = _extract_axis(
                mdata["all_results"], cfg
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
            }

        speed = _extract_speed(mdata["all_results"])
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
        })

    for dim, cfg in AXIS_CONFIG.items():
        scores = [
            (sc["model_name"], sc["dimensions"][dim]["primary"])
            for sc in scorecards
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
        # Approximate when CI columns empty (should be rare after v2 runners).
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
