"""Portable export/import (WP9)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.session import get_db
from benchbase.scoring import compute_model_scorecard

router = APIRouter()

_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{8,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]+", re.I),
]


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    if isinstance(obj, str):
        out = obj
        for pat in _SECRET_PATTERNS:
            out = pat.sub("[REDACTED]", out)
        return out
    return obj


class ExportRequest(BaseModel):
    include_raw_items: bool = False
    ranking_cohort: str = "standard_completed"


@router.post("/evaluation-evidence")
async def export_evaluation(body: ExportRequest, db: AsyncSession = Depends(get_db)):
    cards = await compute_model_scorecard(db, ranking_cohort=body.ranking_cohort)
    package = {
        "schema_version": "benchbase.export.v1",
        "ranking_cohort": body.ranking_cohort,
        "scorecards": _redact(cards),
        "content_hash": hashlib.sha256(
            json.dumps(cards, sort_keys=True, default=str).encode()
        ).hexdigest(),
    }
    return package


class ImportRequest(BaseModel):
    package: dict
    dry_run: bool = True


@router.post("/import")
async def import_package(body: ImportRequest):
    if body.package.get("schema_version") != "benchbase.export.v1":
        raise HTTPException(400, "Unsupported schema_version")
    if body.dry_run:
        return {"status": "validated", "inert": True}
    raise HTTPException(501, "Import persistence not enabled; use dry_run")