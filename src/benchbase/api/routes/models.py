"""Model discovery and management routes (BenchBase v2)."""

from __future__ import annotations

import asyncio
import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.base_model import infer_quant_rank, parse_base_model
from benchbase.db.models import Model, ModelStatus
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
    status: str
    is_active: bool
    color: str
    base_model: str | None
    quant_rank: int | None
    last_checked: datetime.datetime | None

    model_config = {"from_attributes": True}


class ModelCreate(BaseModel):
    name: str = Field(description="LiteLLM model ID or display name.")
    endpoint_url: str = Field(description="Base URL of the OpenAI-compatible API.")
    backend_runtime: str | None = Field(default=None, description="Optional backend hint.")
    quantization: str | None = Field(default=None, description="Optional quantization label.")
    host: str | None = Field(default=None, description="Optional host where the model runs.")


class ModelUpdate(BaseModel):
    color: str | None = None
    base_model: str | None = None
    quant_rank: int | None = None
    status: str | None = Field(
        default=None, description="active | unreachable | archived"
    )


class BulkArchiveBody(BaseModel):
    model_ids: list[int]


def _model_out(m: Model) -> ModelOut:
    return ModelOut(
        id=m.id,
        name=m.name,
        endpoint_url=m.endpoint_url,
        backend_runtime=m.backend_runtime,
        quantization=m.quantization,
        host=m.host,
        status=m.status.value if m.status else "unreachable",
        is_active=m.status == ModelStatus.ACTIVE,
        color=m.color,
        base_model=m.base_model,
        quant_rank=m.quant_rank,
        last_checked=m.last_checked,
    )


@router.get("/", operation_id="list_models", response_model=list[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model).order_by(Model.name))
    return [_model_out(m) for m in result.scalars().all()]


@router.post("/", operation_id="add_model", response_model=ModelOut)
async def add_model(body: ModelCreate, db: AsyncSession = Depends(get_db)):
    existing_result = await db.execute(select(Model))
    used_colors = {m.color for m in existing_result.scalars().all() if m.color}
    color = pick_model_color(used_colors)
    model = Model(
        **body.model_dump(),
        color=color,
        base_model=parse_base_model(body.name),
        quant_rank=infer_quant_rank(body.name, body.quantization),
    )
    model.set_status(ModelStatus.UNREACHABLE)
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return _model_out(model)


@router.patch("/{model_id}", operation_id="update_model", response_model=ModelOut)
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
    if body.base_model is not None:
        model.base_model = body.base_model.strip() or parse_base_model(model.name)
    if body.quant_rank is not None:
        model.quant_rank = body.quant_rank
    if body.status is not None:
        try:
            model.set_status(ModelStatus(body.status))
        except ValueError as exc:
            raise HTTPException(400, "status must be active|unreachable|archived") from exc
    await db.commit()
    await db.refresh(model)
    return _model_out(model)


@router.post("/{model_id}/archive", operation_id="archive_model", response_model=ModelOut)
async def archive_model(model_id: int, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    model.set_status(ModelStatus.ARCHIVED)
    await db.commit()
    await db.refresh(model)
    return _model_out(model)


@router.post("/{model_id}/unarchive", operation_id="unarchive_model", response_model=ModelOut)
async def unarchive_model(model_id: int, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    model.set_status(ModelStatus.UNREACHABLE)
    await db.commit()
    await db.refresh(model)
    return _model_out(model)


@router.post("/archive-bulk", operation_id="bulk_archive_models")
async def bulk_archive(body: BulkArchiveBody, db: AsyncSession = Depends(get_db)):
    count = 0
    for mid in body.model_ids:
        model = await db.get(Model, mid)
        if model and model.status != ModelStatus.ARCHIVED:
            model.set_status(ModelStatus.ARCHIVED)
            count += 1
    await db.commit()
    return {"archived": count}


@router.delete("/{model_id}", operation_id="delete_model")
async def delete_model(model_id: int, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    await db.delete(model)
    await db.commit()
    return {"deleted": True}


@router.post("/discover", operation_id="discover_models")
async def discover_models(db: AsyncSession = Depends(get_db)):
    client = LiteLLMClient()
    try:
        discovered = await client.list_models()
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "Unauthorized" in msg:
            raise HTTPException(
                401,
                "LiteLLM returned 401 Unauthorized. Save your API key in Settings first.",
            )
        if "Connection" in msg or "ConnectError" in msg:
            raise HTTPException(
                502,
                f"Could not connect to LiteLLM at {client.base_url}.",
            )
        raise HTTPException(502, f"Failed to query LiteLLM: {msg}")

    if not discovered:
        return {
            "discovered": 0,
            "active": [],
            "unreachable": [],
            "archived_skipped": 0,
            "details": [],
            "checked_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    existing_result = await db.execute(select(Model))
    all_existing = list(existing_result.scalars().all())
    used_colors = {m.color for m in all_existing if m.color}
    existing_by_lower = {m.name.lower(): m for m in all_existing}

    canonical_ids = {
        m.get("id", "").lower(): m.get("id", "")
        for m in discovered
        if m.get("id")
    }

    to_ping: list[Model] = []
    archived_skipped = 0
    details: list[dict] = []

    for m in discovered:
        name = m.get("id", "")
        if not name:
            continue
        existing = existing_by_lower.get(name.lower())
        if existing:
            if existing.status == ModelStatus.ARCHIVED:
                archived_skipped += 1
                continue
            existing.name = name
            existing.endpoint_url = client.base_url
            if not existing.base_model:
                existing.base_model = parse_base_model(name)
            to_ping.append(existing)
        else:
            color = pick_model_color(used_colors)
            used_colors.add(color)
            new_model = Model(
                name=name,
                endpoint_url=client.base_url,
                color=color,
                base_model=parse_base_model(name),
                quant_rank=infer_quant_rank(name),
            )
            new_model.set_status(ModelStatus.UNREACHABLE)
            db.add(new_model)
            await db.flush()
            to_ping.append(new_model)
            existing_by_lower[name.lower()] = new_model

    # Absent from catalog → unreachable (never probe); leave archived alone.
    for model in all_existing:
        if model.status == ModelStatus.ARCHIVED:
            continue
        if model.name.lower() not in canonical_ids:
            model.set_status(ModelStatus.UNREACHABLE)
            model.last_checked = datetime.datetime.now(datetime.UTC)
            details.append(
                {
                    "name": model.name,
                    "status": "unreachable",
                    "error": "Not present in LiteLLM /v1/models",
                }
            )

    active, unreachable, ping_details = await _health_check_models(client, to_ping)
    details.extend(ping_details)
    await db.commit()
    now = datetime.datetime.now(datetime.UTC).isoformat()
    return {
        "discovered": len(discovered),
        "active": [m.name for m in active],
        "unreachable": [m.name for m in unreachable],
        "archived_skipped": archived_skipped,
        "details": details,
        "checked_at": now,
        # Compat fields for older UI:
        "inactive": [m.name for m in unreachable],
        "failures": {d["name"]: d.get("error", "") for d in details if d.get("error")},
    }


@router.post("/recheck", operation_id="recheck_models")
async def recheck_models(db: AsyncSession = Depends(get_db)):
    client = LiteLLMClient()
    result = await db.execute(select(Model))
    all_models = list(result.scalars().all())
    if not all_models:
        return {
            "discovered": 0,
            "active": [],
            "unreachable": [],
            "archived_skipped": 0,
            "details": [],
            "checked_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    try:
        discovered = await client.list_models()
        canonical_ids = {
            m.get("id", "").lower(): m.get("id", "")
            for m in discovered
            if m.get("id")
        }
    except Exception:
        canonical_ids = {}

    details: list[dict] = []
    archived_skipped = 0
    to_ping: list[Model] = []
    for model in all_models:
        if model.status == ModelStatus.ARCHIVED:
            archived_skipped += 1
            continue
        if canonical_ids and model.name.lower() not in canonical_ids:
            model.set_status(ModelStatus.UNREACHABLE)
            model.last_checked = datetime.datetime.now(datetime.UTC)
            details.append(
                {
                    "name": model.name,
                    "status": "unreachable",
                    "error": "Not present in LiteLLM /v1/models",
                }
            )
            continue
        to_ping.append(model)

    active, unreachable, ping_details = await _health_check_models(client, to_ping)
    details.extend(ping_details)
    await db.commit()
    return {
        "discovered": len(all_models),
        "active": [m.name for m in active],
        "unreachable": [m.name for m in unreachable],
        "archived_skipped": archived_skipped,
        "details": details,
        "checked_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "inactive": [m.name for m in unreachable],
        "failures": {d["name"]: d.get("error", "") for d in details if d.get("error")},
    }


async def _health_check_models(
    client: LiteLLMClient,
    models: list[Model],
) -> tuple[list[Model], list[Model], list[dict]]:
    now = datetime.datetime.now(datetime.UTC)
    active: list[Model] = []
    unreachable: list[Model] = []
    details: list[dict] = []
    sem = asyncio.Semaphore(5)

    async def check_one(model: Model) -> tuple[Model, bool, str]:
        async with sem:
            ok, detail = await client.ping_model_health(model.name, timeout=15)
        return model, ok, detail

    results = await asyncio.gather(*(check_one(model) for model in models))
    for model, ok, detail in results:
        model.last_checked = now
        if ok:
            model.set_status(ModelStatus.ACTIVE)
            active.append(model)
            details.append({"name": model.name, "status": "active", "error": ""})
        else:
            model.set_status(ModelStatus.UNREACHABLE)
            unreachable.append(model)
            details.append(
                {
                    "name": model.name,
                    "status": "unreachable",
                    "error": (detail or "health check failed")[:200],
                }
            )
    return active, unreachable, details
