"""Read-only capability exchange API (WP9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.scoring import compute_model_scorecard
from benchbase.db.session import get_db

router = APIRouter()


@router.get("/deployments")
async def list_deployment_capabilities(db: AsyncSession = Depends(get_db)):
    cards = await compute_model_scorecard(db)
    out = []
    for sc in cards:
        out.append({
            "model_name": sc["model_name"],
            "best_tier": sc.get("best_tier"),
            "cohort_eligible": sc.get("cohort_eligible"),
            "compatibility": {
                axis: sc["dimensions"][axis].get("compatibility_class")
                for axis in sc.get("dimensions", {})
            },
            "status": sc.get("status"),
        })
    return {"schema_version": "benchbase.capabilities.v1", "deployments": out}