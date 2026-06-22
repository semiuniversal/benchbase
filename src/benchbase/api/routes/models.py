"""Model discovery and management routes."""

from __future__ import annotations

import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Model
from benchbase.db.session import get_db
from benchbase.litellm_client import LiteLLMClient
from benchbase.model_colors import is_valid_model_color, pick_model_color

router = APIRouter()


class ModelOut(BaseModel):
    id: int
    name: str
    endpoint_url: str
    backend_runtime: str | None
    quantization: str | None
    host: str | None
    is_active: bool
    color: str
    last_checked: datetime.datetime | None

    model_config = {"from_attributes": True}


class ModelCreate(BaseModel):
    name: str
    endpoint_url: str
    backend_runtime: str | None = None
    quantization: str | None = None
    host: str | None = None


class ModelUpdate(BaseModel):
    color: str | None = None


@router.get("/", response_model=list[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model).order_by(Model.name))
    return result.scalars().all()


@router.post("/", response_model=ModelOut)
async def add_model(body: ModelCreate, db: AsyncSession = Depends(get_db)):
    existing_result = await db.execute(select(Model))
    used_colors = {m.color for m in existing_result.scalars().all() if m.color}
    color = pick_model_color(used_colors)
    model = Model(**body.model_dump(), color=color)
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


@router.patch("/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: int, body: ModelUpdate, db: AsyncSession = Depends(get_db)
):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    if body.color is not None:
        if not is_valid_model_color(body.color):
            raise HTTPException(400, "Color must be a Mantine palette name")
        model.color = body.color
    await db.commit()
    await db.refresh(model)
    return model


@router.delete("/{model_id}")
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    await db.delete(model)
    await db.commit()
    return {"deleted": True}


@router.post("/discover")
async def discover_models(db: AsyncSession = Depends(get_db)):
    """Discover models from LiteLLM, upsert into DB, and health-check each one."""
    client = LiteLLMClient()

    try:
        discovered = await client.list_models()
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "Unauthorized" in msg:
            raise HTTPException(
                401,
                "LiteLLM returned 401 Unauthorized. "
                "Make sure you have saved your API key in Settings before discovering models.",
            )
        if "Connection" in msg or "ConnectError" in msg:
            raise HTTPException(
                502,
                f"Could not connect to LiteLLM at {client.base_url}. "
                "Check the Base URL in Settings and make sure the service is running.",
            )
        raise HTTPException(502, f"Failed to query LiteLLM: {msg}")

    if not discovered:
        return {"discovered": 0, "active": [], "inactive": []}

    existing_result = await db.execute(select(Model))
    used_colors = {m.color for m in existing_result.scalars().all() if m.color}

    models_to_check: list[Model] = []
    for m in discovered:
        name = m.get("id", "")
        if not name:
            continue
        result = await db.execute(select(Model).where(Model.name == name))
        existing = result.scalar_one_or_none()
        if existing:
            existing.endpoint_url = client.base_url
            models_to_check.append(existing)
        else:
            color = pick_model_color(used_colors)
            used_colors.add(color)
            new_model = Model(name=name, endpoint_url=client.base_url, color=color)
            db.add(new_model)
            await db.flush()
            models_to_check.append(new_model)

    active, inactive = await _health_check_models(client, models_to_check)
    await db.commit()

    return {
        "discovered": len(discovered),
        "active": [m.name for m in active],
        "inactive": [m.name for m in inactive],
    }


@router.post("/recheck")
async def recheck_models(db: AsyncSession = Depends(get_db)):
    """Re-ping all existing models without re-querying /v1/models."""
    client = LiteLLMClient()
    result = await db.execute(select(Model))
    all_models = list(result.scalars().all())

    if not all_models:
        return {"discovered": 0, "active": [], "inactive": []}

    active, inactive = await _health_check_models(client, all_models)
    await db.commit()

    return {
        "discovered": len(all_models),
        "active": [m.name for m in active],
        "inactive": [m.name for m in inactive],
    }


async def _health_check_models(
    client: LiteLLMClient, models: list[Model]
) -> tuple[list[Model], list[Model]]:
    """Ping each model sequentially and update is_active / last_checked."""
    now = datetime.datetime.now(datetime.UTC)
    active: list[Model] = []
    inactive: list[Model] = []

    for model in models:
        ok = await client.ping_model(model.name, timeout=60)
        model.is_active = ok
        model.last_checked = now
        if ok:
            active.append(model)
        else:
            inactive.append(model)

    return active, inactive
