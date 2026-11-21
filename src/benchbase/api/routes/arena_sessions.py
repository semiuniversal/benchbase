"""Persisted Arena sessions (WP5b)."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import ArenaSession
from benchbase.db.session import get_db

router = APIRouter()


class ArenaSessionCreate(BaseModel):
    title: str | None = None
    prompt: str = Field(..., min_length=1)
    models: list[str] = Field(..., min_length=1)
    transcript: dict | None = None


@router.post("")
async def save_session(body: ArenaSessionCreate, db: AsyncSession = Depends(get_db)):
    row = ArenaSession(
        title=body.title,
        prompt_json=json.dumps({"prompt": body.prompt}),
        models_json=json.dumps(body.models),
        transcript_json=json.dumps(body.transcript) if body.transcript else None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "created_at": row.created_at.isoformat()}


@router.get("")
async def list_sessions(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ArenaSession).order_by(ArenaSession.id.desc()).limit(50))).scalars()
    return [
        {
            "id": r.id,
            "title": r.title,
            "created_at": r.created_at.isoformat() if isinstance(r.created_at, datetime) else r.created_at,
        }
        for r in rows
    ]


@router.get("/{session_id}")
async def get_session(session_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.get(ArenaSession, session_id)
    if not row:
        raise HTTPException(404, "Session not found")
    return {
        "id": row.id,
        "title": row.title,
        "prompt": json.loads(row.prompt_json),
        "models": json.loads(row.models_json),
        "transcript": json.loads(row.transcript_json) if row.transcript_json else None,
    }