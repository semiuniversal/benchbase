"""Model discovery and management routes."""

from __future__ import annotations

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
    """Discover models from the configured LiteLLM proxy."""
    client = LiteLLMClient()
    discovered = await client.list_models()
    added = []
    for m in discovered:
        exists = await db.execute(select(Model).where(Model.name == m["id"]))
        if exists.scalar_one_or_none():
            continue
        model = Model(name=m["id"], endpoint_url=client.base_url)
        db.add(model)
        added.append(m["id"])
    await db.commit()
    return {"discovered": len(discovered), "added": added}
