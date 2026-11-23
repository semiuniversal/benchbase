"""Portable export/import (WP9)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import CreativeAttempt, CreativeChallengeRevision
from benchbase.db.session import get_db
from benchbase.scoring import compute_model_scorecard

router = APIRouter()

REPO = Path(__file__).resolve().parents[4]
IMPORT_DIR = REPO / "docker" / "data" / "imports"
CHALLENGE_PROMPT = REPO / "corpus" / "creative" / "volcano-skunk-v1" / "prompt.txt"

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
        "package_type": "evaluation_evidence",
        "ranking_cohort": body.ranking_cohort,
        "scorecards": _redact(cards),
        "content_hash": hashlib.sha256(
            json.dumps(cards, sort_keys=True, default=str).encode()
        ).hexdigest(),
    }
    return package


@router.post("/challenge")
async def export_challenge(db: AsyncSession = Depends(get_db)):
    if not CHALLENGE_PROMPT.is_file():
        raise HTTPException(500, "Challenge fixture missing")
    text = CHALLENGE_PROMPT.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    rev = (
        await db.execute(
            select(CreativeChallengeRevision).where(
                CreativeChallengeRevision.challenge_id == "volcano-skunk-v1"
            )
        )
    ).scalar_one_or_none()
    package = {
        "schema_version": "benchbase.export.v1",
        "package_type": "challenge",
        "challenge_id": "volcano-skunk-v1",
        "prompt_sha256": digest,
        "prompt": text,
        "revision_id": rev.id if rev else None,
        "content_hash": digest,
    }
    return _redact(package)


class CreativeExportRequest(BaseModel):
    attempt_uuid: str


@router.post("/creative-artifact")
async def export_creative_artifact(
    body: CreativeExportRequest, db: AsyncSession = Depends(get_db)
):
    row = (
        await db.execute(
            select(CreativeAttempt).where(CreativeAttempt.attempt_uuid == body.attempt_uuid)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Attempt not found")
    package = {
        "schema_version": "benchbase.export.v1",
        "package_type": "creative_artifact",
        "attempt_uuid": row.attempt_uuid,
        "status": row.status,
        "rating": row.rating,
        "notes": row.notes,
        "telemetry": json.loads(row.telemetry_json or "{}"),
        "workspace_path": None,
        "imported": False,
        "verified_local": True,
        "content_hash": hashlib.sha256(
            json.dumps(
                {
                    "uuid": row.attempt_uuid,
                    "status": row.status,
                    "rating": row.rating,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    }
    return _redact(package)


class ImportRequest(BaseModel):
    package: dict
    dry_run: bool = True
    persist: bool = False


def _validate_package(package: dict) -> str:
    ver = package.get("schema_version")
    if ver != "benchbase.export.v1":
        raise HTTPException(400, "Unsupported schema_version")
    if package.get("content_hash") and not isinstance(package["content_hash"], str):
        raise HTTPException(400, "Invalid content_hash")
    size = len(json.dumps(package))
    if size > 50_000_000:
        raise HTTPException(413, "Package too large")
    return package.get("package_type") or "evaluation_evidence"


@router.post("/import")
async def import_package(body: ImportRequest):
    pkg_type = _validate_package(body.package)
    if body.dry_run:
        return {"status": "validated", "inert": True, "package_type": pkg_type}
    if not body.persist:
        return {
            "status": "validated",
            "inert": True,
            "hint": "Set persist=true to store import bundle (still not applied to rankings)",
        }
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    import_id = uuid.uuid4().hex
    path = IMPORT_DIR / f"{import_id}.json"
    payload = {
        **body.package,
        "import_id": import_id,
        "imported": True,
        "verified_local": False,
    }
    path.write_text(json.dumps(_redact(payload), indent=2), encoding="utf-8")
    return {
        "status": "stored",
        "inert": True,
        "import_id": import_id,
        "path": str(path),
        "package_type": pkg_type,
    }