"""Evidence observation API (WP3)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import EvidenceObservation
from benchbase.db.session import get_db
from benchbase.evidence.store import artifact_root

router = APIRouter()


@router.get("/observations")
async def list_observations(
    run_id: int | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(EvidenceObservation).order_by(EvidenceObservation.id.desc()).limit(limit)
    if run_id is not None:
        stmt = stmt.where(EvidenceObservation.run_id == run_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "run_id": r.run_id,
            "item_id": r.item_id,
            "manifest_path": r.manifest_path,
            "content_hash": r.content_hash,
            "schema_version": r.schema_version,
        }
        for r in rows
    ]


@router.get("/observations/{observation_id}")
async def get_observation(observation_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(EvidenceObservation, observation_id)
    if not row:
        raise HTTPException(404, "Observation not found")
    path = artifact_root() / row.manifest_path
    if not path.is_file():
        raise HTTPException(404, "Manifest file missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, "Invalid manifest JSON") from exc
    return {
        "id": row.id,
        "run_id": row.run_id,
        "item_id": row.item_id,
        "content_hash": row.content_hash,
        "payload": payload,
    }