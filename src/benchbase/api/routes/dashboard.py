"""Dashboard actionable headlines API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.dashboard_headlines import fetch_dashboard_headlines
from benchbase.db.session import get_db

router = APIRouter()


@router.get(
    "/headlines",
    operation_id="get_dashboard_headlines",
    summary="Actionable dashboard headlines",
)
async def get_dashboard_headlines(db: AsyncSession = Depends(get_db)):
    return await fetch_dashboard_headlines(db)