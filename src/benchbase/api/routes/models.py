"""Model discovery and management routes."""

from __future__ import annotations

import asyncio
import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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
    name: str = Field(description="LiteLLM model ID or display name.")
    endpoint_url: str = Field(description="Base URL of the OpenAI-compatible API.")
    backend_runtime: str | None = Field(default=None, description="Optional backend hint.")
    quantization: str | None = Field(default=None, description="Optional quantization label.")
    host: str | None = Field(default=None, description="Optional host where the model runs.")


class ModelUpdate(BaseModel):
    color: str | None = Field(
        default=None,
        description="Mantine palette color name for UI display.",
    )


@router.get(
    "/",
    operation_id="list_models",
    summary="List models",
    description="Return all models registered in BenchBase, ordered by name.",
    response_model=list[ModelOut],
)
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model).order_by(Model.name))
    return result.scalars().all()


@router.post(
    "/",
    operation_id="add_model",
    summary="Add a model",
    description="Manually register a model (discover_models is preferred for LiteLLM sync).",
    response_model=ModelOut,
)
async def add_model(body: ModelCreate, db: AsyncSession = Depends(get_db)):
    existing_result = await db.execute(select(Model))
    used_colors = {m.color for m in existing_result.scalars().all() if m.color}
    color = pick_model_color(used_colors)
    model = Model(**body.model_dump(), color=color)
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


@router.patch(
    "/{model_id}",
    operation_id="update_model",
    summary="Update a model",
    description="Update model metadata (currently supports color only).",
    response_model=ModelOut,
)
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


@router.delete(
    "/{model_id}",
    operation_id="delete_model",
    summary="Delete a model",
    description="Remove a model from the database.",
)
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    await db.delete(model)
    await db.commit()
    return {"deleted": True}


@router.post(
    "/discover",
    operation_id="discover_models",
    summary="Discover models from LiteLLM",
    description=(
        "Query LiteLLM /v1/models, upsert models into the database, "
        "and health-check each one sequentially."
    ),
)
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
        return {"discovered": 0, "active": [], "inactive": [], "failures": {}}

    existing_result = await db.execute(select(Model))
    all_existing = list(existing_result.scalars().all())
    used_colors = {m.color for m in all_existing if m.color}
    existing_by_lower = {m.name.lower(): m for m in all_existing}

    models_to_check: list[Model] = []
    for m in discovered:
        name = m.get("id", "")
        if not name:
            continue
        existing = existing_by_lower.get(name.lower())
        if existing:
            existing.name = name
            existing.endpoint_url = client.base_url
            models_to_check.append(existing)
        else:
            color = pick_model_color(used_colors)
            used_colors.add(color)
            new_model = Model(name=name, endpoint_url=client.base_url, color=color)
            db.add(new_model)
            await db.flush()
            models_to_check.append(new_model)
            existing_by_lower[name.lower()] = new_model

    canonical_ids = {
        m.get("id", "").lower(): m.get("id", "")
        for m in discovered
        if m.get("id")
    }
    active, inactive, failures = await _health_check_models(
        client, models_to_check, canonical_ids
    )
    await db.commit()

    return {
        "discovered": len(discovered),
        "active": [m.name for m in active],
        "inactive": [m.name for m in inactive],
        "failures": failures,
    }


@router.post(
    "/recheck",
    operation_id="recheck_models",
    summary="Re-check model health",
    description="Ping all registered models without re-querying LiteLLM /v1/models.",
)
async def recheck_models(db: AsyncSession = Depends(get_db)):
    """Re-ping all existing models without re-querying /v1/models."""
    client = LiteLLMClient()
    result = await db.execute(select(Model))
    all_models = list(result.scalars().all())

    if not all_models:
        return {"discovered": 0, "active": [], "inactive": [], "failures": {}}

    try:
        discovered = await client.list_models()
        canonical_ids = {
            m.get("id", "").lower(): m.get("id", "")
            for m in discovered
            if m.get("id")
        }
    except Exception:
        canonical_ids = {}

    active, inactive, failures = await _health_check_models(
        client, all_models, canonical_ids
    )
    await db.commit()

    return {
        "discovered": len(all_models),
        "active": [m.name for m in active],
        "inactive": [m.name for m in inactive],
        "failures": failures,
    }


async def _health_check_models(
    client: LiteLLMClient,
    models: list[Model],
    canonical_ids: dict[str, str] | None = None,
) -> tuple[list[Model], list[Model], dict[str, str]]:
    """Ping models concurrently and update is_active / last_checked."""
    now = datetime.datetime.now(datetime.UTC)
    active: list[Model] = []
    inactive: list[Model] = []
    failures: dict[str, str] = {}
    id_map = canonical_ids or {}
    sem = asyncio.Semaphore(5)

    async def check_one(model: Model) -> tuple[Model, str, bool, str]:
        ping_id = id_map.get(model.name.lower(), model.name)
        async with sem:
            ok, detail = await client.ping_model_health(ping_id, timeout=15)
        return model, ping_id, ok, detail

    results = await asyncio.gather(*(check_one(model) for model in models))

    for model, ping_id, ok, detail in results:
        if ping_id != model.name and ok:
            model.name = ping_id
        model.is_active = ok
        model.last_checked = now
        if ok:
            active.append(model)
        else:
            inactive.append(model)
            if detail:
                failures[model.name] = detail

    return active, inactive, failures
