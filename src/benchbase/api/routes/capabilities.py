"""Read-only capability exchange API (WP9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.scoring import compute_model_scorecard
from benchbase.db.session import get_db

router = APIRouter()

AXIS_LABELS = (
    "smoke",
    "knowledge",
    "reasoning",
    "math",
    "coding",
    "tool_calling",
    "instruction",
    "structured",
    "long_context",
    "speed",
)


@router.get("/deployments")
async def list_deployment_capabilities(
    db: AsyncSession = Depends(get_db),
    ranking_cohort: str = Query("standard_completed"),
):
    cards = await compute_model_scorecard(db, ranking_cohort=ranking_cohort)
    out = []
    for sc in cards:
        dims = sc.get("dimensions") or {}
        axis_payload = {}
        for axis in AXIS_LABELS:
            row = dims.get(axis) or {}
            score = row.get("score")
            axis_payload[axis] = {
                "score": score,
                "method": row.get("method") or row.get("primary_method"),
                "n_items": row.get("n_items"),
                "compatibility_class": row.get("compatibility_class"),
                "status": "measured" if score is not None else "unknown",
            }
        speed = sc.get("speed") or {}
        out.append({
            "model_name": sc["model_name"],
            "best_tier": sc.get("best_tier"),
            "ranking_cohort": ranking_cohort,
            "cohort_eligible": sc.get("cohort_eligible"),
            "axes": axis_payload,
            "decode_tps": speed.get("decode_tps"),
            "decode_tps_32k": speed.get("decode_tps_32k"),
            "decode_invalid_reason": speed.get("decode_invalid_reason"),
            "limitations": sc.get("status"),
        })
    return {"schema_version": "benchbase.capabilities.v2", "deployments": out}