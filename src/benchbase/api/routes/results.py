"""Results query and comparison routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import Result, Run
from benchbase.db.session import get_db
from benchbase.scoring import compute_model_scorecard, compute_scorecard

router = APIRouter()


class ResultOut(BaseModel):
    id: int
    run_id: int
    task_name: str
    score: float | None
    metrics: dict | None = None

    model_config = {"from_attributes": True}


@router.get(
    "/by-run/{run_id}",
    operation_id="get_results_by_run",
    summary="Get results for a run",
    description="Return all scored task results for a single benchmark run.",
    response_model=list[ResultOut],
)
async def results_for_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    stmt = select(Result).where(Result.run_id == run_id)
    rows = await db.execute(stmt)
    results = rows.scalars().all()
    return [
        ResultOut(
            id=r.id,
            run_id=r.run_id,
            task_name=r.task_name,
            score=r.score,
            metrics=json.loads(r.metrics_json) if r.metrics_json else None,
        )
        for r in results
    ]


class ComparisonEntry(BaseModel):
    model_name: str
    suite_name: str
    category: str
    scores: dict


@router.get(
    "/compare",
    operation_id="compare_runs",
    summary="Compare benchmark runs",
    description="Compare task scores across multiple runs by run ID.",
    response_model=list[ComparisonEntry],
)
async def compare_runs(
    run_ids: list[int] = Query(..., description="Run IDs to compare."),
    db: AsyncSession = Depends(get_db),
):
    """Compare results across multiple runs."""
    entries: list[ComparisonEntry] = []
    for run_id in run_ids:
        run = await db.get(
            Run, run_id, options=[selectinload(Run.model), selectinload(Run.suite)]
        )
        if not run:
            continue
        stmt = select(Result).where(Result.run_id == run_id)
        rows = await db.execute(stmt)
        results = rows.scalars().all()
        scores = {}
        for r in results:
            scores[r.task_name] = {
                "score": r.score,
                "metrics": json.loads(r.metrics_json) if r.metrics_json else None,
            }
        entries.append(
            ComparisonEntry(
                model_name=run.model.name,
                suite_name=run.suite.name,
                category=run.suite.category.value,
                scores=scores,
            )
        )
    return entries


@router.get(
    "/scorecard",
    operation_id="get_scorecard",
    summary="Get scorecard for runs",
    description="Ranked scorecard comparing models across dimensions for specific run IDs.",
)
async def scorecard(
    run_ids: list[int] = Query(..., description="Run IDs to include in the scorecard."),
    db: AsyncSession = Depends(get_db),
):
    """Ranked scorecard comparing models across all four dimensions."""
    return await compute_scorecard(run_ids, db)


@router.get(
    "/model-scorecard",
    operation_id="get_model_scorecard",
    summary="Get model scorecard",
    description=(
        "Ranked scorecard for all models with benchmark history "
        "(averaged across completed runs, includes offline models)."
    ),
)
async def model_scorecard(db: AsyncSession = Depends(get_db)):
    """Ranked scorecard for active and historical models (averaged across completed runs)."""
    return await compute_model_scorecard(db)
