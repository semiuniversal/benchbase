"""Model discovery and management routes."""

from __future__ import annotations

import asyncio
import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Model
from benchbase.db.session import get_db
from benchbase.litellm_client import LiteLLMClient

router = APIRouter()


class ModelOut(BaseModel):
    id: int
    name: str
    endpoint_url: str
    backend_runtime: str | None
    quantization: str | None
    host: str | None
    is_active: bool
    last_checked: str | None

    model_config = {"from_attributes": True}


class ModelCreate(BaseModel):
    name: str
    endpoint_url: str
    backend_runtime: str | None = None
    quantization: str | None = None
    host: str | None = None


@router.get("/", response_model=list[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model).order_by(Model.name))
    return result.scalars().all()


@router.post("/", response_model=ModelOut)
async def add_model(body: ModelCreate, db: AsyncSession = Depends(get_db)):
    model = Model(**body.model_dump())
    db.add(model)
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
    discovered = await client.list_models()

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
            new_model = Model(name=name, endpoint_url=client.base_url)
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
    """Ping each model concurrently and update is_active / last_checked."""
    now = datetime.datetime.now(datetime.UTC)

    async def check(model: Model) -> bool:
        ok = await client.ping_model(model.name, timeout=10)
        model.is_active = ok
        model.last_checked = now
        return ok

    results = await asyncio.gather(*(check(m) for m in models))

    active = [m for m, ok in zip(models, results) if ok]
    inactive = [m for m, ok in zip(models, results) if not ok]
    return active, inactive
