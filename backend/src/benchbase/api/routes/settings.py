"""Settings CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from benchbase.config import Settings, load_settings, save_settings

router = APIRouter()


class SettingsUpdate(BaseModel):
    litellm_base_url: str | None = None
    database_url: str | None = None
    theme: str | None = None
    default_models: list[str] | None = None
    benchmark_suites: list[str] | None = None


@router.get("/", response_model=Settings)
async def get_settings():
    return load_settings()


@router.put("/", response_model=Settings)
async def update_settings(body: SettingsUpdate):
    current = load_settings()
    update_data = body.model_dump(exclude_unset=True)
    merged = current.model_copy(update=update_data)
    save_settings(merged)
    return merged
