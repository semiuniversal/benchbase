"""Relative-rank scoring across benchmark dimensions."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Model, Result, Run, RunStatus


DIMENSION_CONFIG: dict[str, dict[str, Any]] = {
    "speed": {
        # Speed = time to usable output. Thinking tokens never count here (see reasoning/coding).
        "primary_prefix": "speed:output_completion",
        "unit": "ms",
        "higher_is_better": False,
        "detail_prefixes": [
            "speed:tg",
            "speed:output_tg",
            "speed:output_ttft",
            "speed:pp",
            "speed:ctx_pp",
        ],
    },
    "coding": {
        "primary_prefix": "coding:",
        "unit": "%",
        "higher_is_better": True,
        "detail_prefixes": [],
    },
    "tool_use": {
        "primary_prefix": "tool_use:",
        "unit": "%",
        "higher_is_better": True,
        "detail_prefixes": [],
    },
    "reasoning": {
        "primary_prefix": "reasoning:",
        "unit": "%",
        "higher_is_better": True,
        "detail_prefixes": [],
    },
}


async def compute_scorecard(
    run_ids: list[int], db: AsyncSession
) -> list[dict[str, Any]]:
    """Compute a ranked scorecard for the given runs."""
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
                "all_results": [],
            }
        models_data[name]["all_results"].extend(results)

    return _build_scorecards(models_data)


async def compute_model_scorecard(db: AsyncSession) -> list[dict[str, Any]]:
    """Scorecard ranked head-to-head across active models and historical (offline) models."""
    completed_ids_result = await db.execute(
        select(Run.model_id).where(Run.status == RunStatus.COMPLETED).distinct()
    )
    completed_model_ids = {row[0] for row in completed_ids_result.all()}

    models_result = await db.execute(select(Model).order_by(Model.name))
    all_models = models_result.scalars().all()
    included = [
        m for m in all_models
        if m.is_active or m.id in completed_model_ids
    ]

    models_data: dict[str, dict[str, Any]] = {}
    for model in included:
        runs_result = await db.execute(
            select(Run)
            .where(Run.model_id == model.id, Run.status == RunStatus.COMPLETED)
            .options(selectinload(Run.results))
        )
        runs = runs_result.scalars().all()
        all_results: list[Result] = []
        for run in runs:
            all_results.extend(run.results)
        models_data[model.name] = {
            "model_name": model.name,
            "model_color": model.color,
            "is_active": model.is_active,
            "has_benchmark_history": len(runs) > 0,
            "all_results": all_results,
        }

    return _build_scorecards(models_data)


def _assign_ranks(
    scored: list[tuple[str, float]],
    *,
    higher_is_better: bool,
) -> dict[str, dict[str, Any]]:
    """Competition ranking (1, 2, 2, 4…) with tie detection."""
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
    """Head-to-head points for a placement among `competitors` models (1st → n-1 pts)."""
    return competitors - rank


def _build_scorecards(models_data: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    scorecards = []
    for model_name, mdata in models_data.items():
        dimensions: dict[str, dict[str, Any]] = {}
        for dim, cfg in DIMENSION_CONFIG.items():
            primary_score, details, sample_count = _extract_dimension(
                mdata["all_results"], cfg
            )
            dimensions[dim] = {
                "primary": primary_score,
                "unit": cfg["unit"],
                "details": details,
                "sample_count": sample_count,
            }
        scorecards.append({
            "model_name": model_name,
            "model_color": mdata.get("model_color"),
            "is_active": mdata.get("is_active"),
            "has_benchmark_history": mdata.get("has_benchmark_history"),
            "dimensions": dimensions,
        })

    for dim, cfg in DIMENSION_CONFIG.items():
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
            sc["dimensions"][d]["borda_points"] for d in DIMENSION_CONFIG
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


def _extract_dimension(
    results: list[Result], cfg: dict[str, Any]
) -> tuple[float | None, dict[str, Any], int]:
    """Extract the primary score, detail scores, and count of primary samples."""
    primary_scores: list[float] = []
    details: dict[str, Any] = {}

    for r in results:
        if r.task_name.startswith(cfg["primary_prefix"]):
            if r.score is not None:
                primary_scores.append(r.score)
                details[r.task_name] = r.score

        for dp in cfg.get("detail_prefixes", []):
            if r.task_name.startswith(dp):
                if r.score is not None:
                    details[r.task_name] = r.score
                if r.metrics_json:
                    try:
                        metrics = json.loads(r.metrics_json)
                        if "e2e_ttft" in metrics and metrics["e2e_ttft"]:
                            details[f"{r.task_name}:ttft_ms"] = metrics["e2e_ttft"]["mean"]
                        if metrics.get("type") == "output_tg" and metrics.get("output_ttft_ms"):
                            ttft = metrics["output_ttft_ms"]
                            if isinstance(ttft, dict) and ttft.get("mean") is not None:
                                details[f"{r.task_name}:output_ttft_ms"] = ttft["mean"]
                    except (json.JSONDecodeError, KeyError):
                        pass

    primary = (
        round(sum(primary_scores) / len(primary_scores), 2) if primary_scores else None
    )
    return primary, details, len(primary_scores)
