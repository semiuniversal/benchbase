"""Relative-rank scoring across benchmark dimensions."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Result, Run


DIMENSION_CONFIG: dict[str, dict[str, Any]] = {
    "speed": {
        "primary_prefix": "speed:tg",
        "unit": "tok/s",
        "higher_is_better": True,
        "detail_prefixes": ["speed:pp", "speed:ctx_pp"],
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
    """Compute a ranked scorecard for the given runs.

    Returns a list of dicts, one per model, with per-dimension ranks,
    primary scores, detail scores, and a composite rank.
    """
    runs_data: list[dict[str, Any]] = []

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

        runs_data.append({
            "run_id": run_id,
            "model_name": run.model.name,
            "category": run.suite.category.value if run.suite else None,
            "results": results,
        })

    models: dict[str, dict[str, Any]] = {}
    for rd in runs_data:
        name = rd["model_name"]
        if name not in models:
            models[name] = {"model_name": name, "all_results": []}
        models[name]["all_results"].extend(rd["results"])

    scorecards = []
    for model_name, mdata in models.items():
        dimensions: dict[str, dict[str, Any]] = {}
        for dim, cfg in DIMENSION_CONFIG.items():
            primary_score, details = _extract_dimension(
                mdata["all_results"], cfg
            )
            dimensions[dim] = {
                "primary": primary_score,
                "unit": cfg["unit"],
                "details": details,
            }
        scorecards.append({
            "model_name": model_name,
            "dimensions": dimensions,
        })

    for dim, cfg in DIMENSION_CONFIG.items():
        scores = []
        for sc in scorecards:
            scores.append((sc["model_name"], sc["dimensions"][dim]["primary"]))

        valid = [(name, s) for name, s in scores if s is not None]
        valid.sort(key=lambda x: x[1], reverse=cfg["higher_is_better"])

        rank_map: dict[str, int] = {}
        for i, (name, score) in enumerate(valid):
            if i > 0 and score == valid[i - 1][1]:
                rank_map[name] = rank_map[valid[i - 1][0]]
            else:
                rank_map[name] = i + 1

        for sc in scorecards:
            sc["dimensions"][dim]["rank"] = rank_map.get(sc["model_name"])

    for sc in scorecards:
        ranks = [
            sc["dimensions"][d]["rank"]
            for d in DIMENSION_CONFIG
            if sc["dimensions"][d]["rank"] is not None
        ]
        sc["composite_rank"] = round(sum(ranks) / len(ranks), 2) if ranks else None

    scorecards.sort(key=lambda x: x["composite_rank"] or 999)
    return scorecards


def _extract_dimension(
    results: list[Result], cfg: dict[str, Any]
) -> tuple[float | None, dict[str, Any]]:
    """Extract the primary score and detail scores for one dimension."""
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
                    except (json.JSONDecodeError, KeyError):
                        pass

    primary = round(sum(primary_scores) / len(primary_scores), 2) if primary_scores else None
    return primary, details
