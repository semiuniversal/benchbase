"""Creative Arena API (WP8, feature-flagged)."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.creative.mock_harness import materialize_static_app
from benchbase.db.models import CreativeAttempt, CreativeChallengeRevision
from benchbase.db.session import get_db

router = APIRouter()
REPO = Path(__file__).resolve().parents[4]
PROMPT_PATH = REPO / "corpus" / "creative" / "volcano-skunk-v1" / "prompt.txt"


def _creative_enabled() -> bool:
    import os

    if os.environ.get("BENCHBASE_CREATIVE_ARENA", "").lower() in ("1", "true", "yes"):
        return True
    return load_settings().creative_arena_enabled


class MockAttemptBody(BaseModel):
    model_name: str = Field(..., min_length=1)


@router.get("/challenges")
async def list_challenges():
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    text = PROMPT_PATH.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return [
        {
            "id": "volcano-skunk-v1",
            "title": "Volcano & Skunk",
            "prompt_sha256": digest,
        }
    ]


@router.post("/attempts/mock")
async def create_mock_attempt(body: MockAttemptBody, db: AsyncSession = Depends(get_db)):
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    if not PROMPT_PATH.is_file():
        raise HTTPException(500, "Challenge fixture missing")
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    rev = (
        await db.execute(
            select(CreativeChallengeRevision).where(
                CreativeChallengeRevision.challenge_id == "volcano-skunk-v1"
            )
        )
    ).scalar_one_or_none()
    if rev is None:
        rev = CreativeChallengeRevision(
            challenge_id="volcano-skunk-v1",
            title="Volcano & Skunk",
            prompt_sha256=digest,
            prompt_path=str(PROMPT_PATH.relative_to(REPO)),
        )
        db.add(rev)
        await db.flush()

    attempt_id = str(uuid.uuid4())
    ws = REPO / "data" / "creative" / attempt_id
    materialize_static_app(ws, prompt)
    attempt = CreativeAttempt(
        attempt_uuid=attempt_id,
        challenge_revision_id=rev.id,
        status="completed",
        workspace_path=str(ws),
        telemetry_json=json.dumps({"harness": "mock", "model_name": body.model_name}),
    )
    db.add(attempt)
    await db.commit()
    return {"attempt_uuid": attempt_id, "status": "completed"}


@router.get("/attempts/{attempt_uuid}/source")
async def list_source(attempt_uuid: str, db: AsyncSession = Depends(get_db)):
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    attempt = (
        await db.execute(
            select(CreativeAttempt).where(CreativeAttempt.attempt_uuid == attempt_uuid)
        )
    ).scalar_one_or_none()
    if not attempt or not attempt.workspace_path:
        raise HTTPException(404, "Attempt not found")
    root = Path(attempt.workspace_path) / "project"
    if not root.is_dir():
        raise HTTPException(404, "No source tree")
    files = sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and "node_modules" not in p.parts
    )
    return {"attempt_uuid": attempt_uuid, "files": files}


@router.get("/attempts/{attempt_uuid}/source/{file_path:path}")
async def read_source_file(attempt_uuid: str, file_path: str, db: AsyncSession = Depends(get_db)):
    from benchbase.creative.worker import validate_workspace_path

    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    attempt = (
        await db.execute(
            select(CreativeAttempt).where(CreativeAttempt.attempt_uuid == attempt_uuid)
        )
    ).scalar_one_or_none()
    if not attempt or not attempt.workspace_path:
        raise HTTPException(404, "Attempt not found")
    root = Path(attempt.workspace_path) / "project"
    target = validate_workspace_path(root, file_path)
    if target is None or not target.is_file():
        raise HTTPException(400, "Invalid path")
    if target.stat().st_size > 512_000:
        raise HTTPException(413, "File too large for inline view")
    return {
        "path": file_path,
        "content": target.read_text(encoding="utf-8", errors="replace"),
    }