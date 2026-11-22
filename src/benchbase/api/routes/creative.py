"""Creative Arena API (WP8, feature-flagged)."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from benchbase.config import load_settings
from benchbase.creative.attempt_tasks import schedule_mock_attempt, terminal_event
from benchbase.creative.events import stream_events
from benchbase.creative.workspace import provision_attempt_workspace
from benchbase.db.models import CreativeAttempt, CreativeChallengeRevision
from benchbase.db.session import get_db

router = APIRouter()
REPO = Path(__file__).resolve().parents[4]
PROMPT_PATH = REPO / "corpus" / "creative" / "volcano-skunk-v1" / "prompt.txt"
CHALLENGE_ID = "volcano-skunk-v1"


def _creative_enabled() -> bool:
    import os

    if os.environ.get("BENCHBASE_CREATIVE_ARENA", "").lower() in ("1", "true", "yes"):
        return True
    return load_settings().creative_arena_enabled


class StartAttemptBody(BaseModel):
    model_name: str = Field(..., min_length=1)
    harness: str = Field(default="mock", description="mock until OpenCode pin qualifies")


class MockAttemptBody(BaseModel):
    model_name: str = Field(..., min_length=1)


async def _ensure_challenge_revision(db: AsyncSession) -> CreativeChallengeRevision:
    if not PROMPT_PATH.is_file():
        raise HTTPException(500, "Challenge fixture missing")
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    rev = (
        await db.execute(
            select(CreativeChallengeRevision).where(
                CreativeChallengeRevision.challenge_id == CHALLENGE_ID
            )
        )
    ).scalar_one_or_none()
    if rev is None:
        rev = CreativeChallengeRevision(
            challenge_id=CHALLENGE_ID,
            title="Volcano & Skunk",
            prompt_sha256=digest,
            prompt_path=str(PROMPT_PATH.relative_to(REPO)),
        )
        db.add(rev)
        await db.flush()
    return rev


async def _get_attempt(db: AsyncSession, attempt_uuid: str) -> CreativeAttempt:
    attempt = (
        await db.execute(
            select(CreativeAttempt).where(CreativeAttempt.attempt_uuid == attempt_uuid)
        )
    ).scalar_one_or_none()
    if not attempt or not attempt.workspace_path:
        raise HTTPException(404, "Attempt not found")
    return attempt


@router.get("/challenges")
async def list_challenges():
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    text = PROMPT_PATH.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return [
        {
            "id": CHALLENGE_ID,
            "title": "Volcano & Skunk",
            "prompt_sha256": digest,
        }
    ]


@router.post("/attempts/start")
async def start_attempt(body: StartAttemptBody, db: AsyncSession = Depends(get_db)):
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    if body.harness not in ("mock", "opencode"):
        raise HTTPException(400, "harness must be mock or opencode")
    if body.harness == "opencode":
        raise HTTPException(
            501,
            "OpenCode live harness not qualified yet; use mock while skills are translated",
        )

    rev = await _ensure_challenge_revision(db)
    attempt_id = str(uuid.uuid4())
    root = provision_attempt_workspace(attempt_id, model_name=body.model_name, harness=body.harness)
    attempt = CreativeAttempt(
        attempt_uuid=attempt_id,
        challenge_revision_id=rev.id,
        status="pending",
        workspace_path=str(root),
        telemetry_json=json.dumps({"harness": body.harness, "model_name": body.model_name}),
    )
    db.add(attempt)
    await db.commit()

    schedule_mock_attempt(root, attempt_id, body.model_name)
    return {"attempt_uuid": attempt_id, "status": "pending", "harness": body.harness}


@router.post("/attempts/mock")
async def create_mock_attempt(body: MockAttemptBody, db: AsyncSession = Depends(get_db)):
    """Backward-compatible alias for start (mock)."""
    return await start_attempt(StartAttemptBody(model_name=body.model_name, harness="mock"), db)


@router.get("/attempts")
async def list_attempts(
    limit: int = 40,
    db: AsyncSession = Depends(get_db),
):
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    cap = max(1, min(limit, 100))
    rows = (
        await db.execute(
            select(CreativeAttempt).order_by(CreativeAttempt.created_at.desc()).limit(cap)
        )
    ).scalars().all()
    out = []
    for row in rows:
        telem = json.loads(row.telemetry_json or "{}")
        out.append(
            {
                "attempt_uuid": row.attempt_uuid,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "model_name": telem.get("model_name"),
                "harness": telem.get("harness", "mock"),
                "rating": row.rating,
            }
        )
    return out


@router.get("/attempts/{attempt_uuid}")
async def get_attempt(attempt_uuid: str, db: AsyncSession = Depends(get_db)):
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    attempt = await _get_attempt(db, attempt_uuid)
    return {
        "attempt_uuid": attempt.attempt_uuid,
        "status": attempt.status,
        "workspace_path": attempt.workspace_path,
        "telemetry": json.loads(attempt.telemetry_json or "{}"),
    }


@router.get("/attempts/{attempt_uuid}/events")
async def attempt_events(attempt_uuid: str, db: AsyncSession = Depends(get_db)):
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    attempt = await _get_attempt(db, attempt_uuid)
    root = Path(attempt.workspace_path)
    term = terminal_event(attempt_uuid)

    async def gen():
        async for row in stream_events(attempt_uuid, root, terminal_status=term):
            yield {"event": "creative", "data": json.dumps(row, ensure_ascii=False)}
        from benchbase.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(CreativeAttempt).where(CreativeAttempt.attempt_uuid == attempt_uuid)
                )
            ).scalar_one_or_none()
            status = row.status if row else "unknown"
        yield {"event": "done", "data": json.dumps({"status": status})}

    return EventSourceResponse(gen())


@router.get("/attempts/{attempt_uuid}/source")
async def list_source(attempt_uuid: str, db: AsyncSession = Depends(get_db)):
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    attempt = await _get_attempt(db, attempt_uuid)
    root = Path(attempt.workspace_path) / "project"
    if not root.is_dir():
        return {"attempt_uuid": attempt_uuid, "files": []}
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
    attempt = await _get_attempt(db, attempt_uuid)
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


@router.get("/attempts/{attempt_uuid}/preview")
@router.get("/attempts/{attempt_uuid}/preview/")
async def preview_index(attempt_uuid: str, db: AsyncSession = Depends(get_db)):
    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    attempt = await _get_attempt(db, attempt_uuid)
    root = Path(attempt.workspace_path) / "project"
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(404, "No preview yet")
    return FileResponse(index, media_type="text/html")


@router.get("/attempts/{attempt_uuid}/preview/{asset_path:path}")
async def preview_asset(
    attempt_uuid: str, asset_path: str, db: AsyncSession = Depends(get_db)
):
    from benchbase.creative.worker import validate_workspace_path

    if not _creative_enabled():
        raise HTTPException(403, "Creative Arena disabled")
    attempt = await _get_attempt(db, attempt_uuid)
    root = Path(attempt.workspace_path) / "project"
    target = validate_workspace_path(root, asset_path)
    if target is None or not target.is_file():
        raise HTTPException(404, "Not found")
    media, _ = mimetypes.guess_type(str(target))
    return FileResponse(target, media_type=media or "application/octet-stream")