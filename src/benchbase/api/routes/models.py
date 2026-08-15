"""Model discovery and management routes (BenchBase v2)."""

from __future__ import annotations

import asyncio
import datetime
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.base_model import infer_quant_rank, parse_base_model
from benchbase.db.models import (
    BenchmarkAxis,
    Model,
    ModelStatus,
    Result,
    Run,
    RunStatus,
    RunTier,
)
from benchbase.db.session import get_db
from benchbase.litellm_client import LiteLLMClient
from benchbase.model_colors import is_valid_model_color, pick_model_color
from benchbase.model_eligibility import (
    list_finalist_eligible_models,
    model_finalist_eligible,
    model_has_completed_tier,
)

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
    supports_vision: bool = False
    notes: str | None = None
    context_window: int | None = None
    context_window_manual: bool = False
    vram_gb: float | None = None
    max_output_tokens: int | None = None
    litellm_model_info: dict[str, Any] | None = None
    last_checked: datetime.datetime | None = None
    finalist_eligible: bool | None = None

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
    notes: str | None = None
    context_window: int | None = Field(default=None, ge=0)
    vram_gb: float | None = Field(default=None, ge=0)
    status: str | None = Field(
        default=None, description="active | unreachable | archived"
    )


class BulkArchiveBody(BaseModel):
    model_ids: list[int]


class ModelTierSummary(BaseModel):
    smoke_completed: bool = False
    standard_completed: bool = False
    thorough_completed: bool = False
    finalist_eligible: bool = False


class AgenticMetricsSnippet(BaseModel):
    run_id: int | None = None
    n_passed: int | None = None
    n_attempts: int | None = None
    mean_tool_calls: float | None = None
    mean_turns: float | None = None
    geo_mean_teff_vs_self: float | None = None
    display: str | None = None
    suite: str | None = None


class ModelRunSummary(BaseModel):
    id: int
    status: str
    tier: str | None = None
    suite_id: int
    suite_name: str | None = None
    axis: str | None = None
    finalist: bool = False
    started_at: datetime.datetime | None = None
    completed_at: datetime.datetime | None = None
    display_label: str | None = None
    score: float | None = None
    n_passed: int | None = None
    n_attempts: int | None = None
    mean_tool_calls: float | None = None
    mean_turns: float | None = None
    geo_mean_teff_vs_self: float | None = None


class ModelDetailOut(BaseModel):
    model: ModelOut
    tiers: ModelTierSummary
    last_agentic: AgenticMetricsSnippet | None = None
    recent_runs: list[ModelRunSummary] = []


def _litellm_info_dict(m: Model) -> dict[str, Any] | None:
    raw = getattr(m, "litellm_model_info_json", None)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _model_out(m: Model, *, finalist_eligible: bool | None = None) -> ModelOut:
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
        supports_vision=bool(getattr(m, "supports_vision", False)),
        notes=getattr(m, "notes", None),
        context_window=getattr(m, "context_window", None),
        context_window_manual=bool(getattr(m, "context_window_manual", False)),
        vram_gb=getattr(m, "vram_gb", None),
        max_output_tokens=getattr(m, "max_output_tokens", None),
        litellm_model_info=_litellm_info_dict(m),
        last_checked=m.last_checked,
        finalist_eligible=finalist_eligible,
    )


def _apply_litellm_info(model: Model, info: dict[str, Any] | None) -> None:
    if not info:
        return
    model.supports_vision = bool(info.get("supports_vision"))
    ctx = info.get("context_window")
    if (
        isinstance(ctx, int)
        and ctx > 0
        and not bool(getattr(model, "context_window_manual", False))
    ):
        model.context_window = ctx
    mout = info.get("max_output_tokens")
    if isinstance(mout, int) and mout > 0:
        model.max_output_tokens = mout
    raw = info.get("raw") if isinstance(info.get("raw"), dict) else {}
    snapshot = {
        "supports_vision": model.supports_vision,
        "context_window": model.context_window,
        "max_output_tokens": model.max_output_tokens,
        **raw,
    }
    model.litellm_model_info_json = json.dumps(snapshot, default=str)


def _run_is_finalist(run: Run) -> bool:
    if run.suite and run.suite.axis == BenchmarkAxis.AGENTIC:
        return True
    try:
        meta = json.loads(run.metadata_json) if run.metadata_json else {}
    except json.JSONDecodeError:
        meta = {}
    return bool(meta.get("finalist"))


def _agentic_from_results(results: list[Result]) -> dict[str, Any]:
    for res in results:
        if not (res.task_name or "").startswith("agentic:"):
            continue
        metrics: dict[str, Any] = {}
        if res.metrics_json:
            try:
                parsed = json.loads(res.metrics_json)
                if isinstance(parsed, dict):
                    metrics = parsed
            except json.JSONDecodeError:
                pass
        return {
            "score": res.score,
            "n_passed": metrics.get("n_passed"),
            "n_attempts": metrics.get("n_attempts"),
            "mean_tool_calls": metrics.get("mean_tool_calls"),
            "mean_turns": metrics.get("mean_turns"),
            "geo_mean_teff_vs_self": metrics.get("geo_mean_teff_vs_self"),
            "display": metrics.get("display"),
            "suite": metrics.get("suite"),
        }
    score = None
    if results:
        score = results[0].score
    return {"score": score}


def _model_run_summary(run: Run) -> ModelRunSummary:
    agentic = _agentic_from_results(list(run.results or []))
    return ModelRunSummary(
        id=run.id,
        status=run.status.value if run.status else "unknown",
        tier=run.tier.value if run.tier else None,
        suite_id=run.suite_id,
        suite_name=run.suite.name if run.suite else None,
        axis=run.suite.axis.value if run.suite and run.suite.axis else None,
        finalist=_run_is_finalist(run),
        started_at=run.started_at,
        completed_at=run.completed_at,
        display_label=agentic.get("display") if isinstance(agentic.get("display"), str) else None,
        score=agentic.get("score") if isinstance(agentic.get("score"), (int, float)) else None,
        n_passed=agentic.get("n_passed") if isinstance(agentic.get("n_passed"), int) else None,
        n_attempts=agentic.get("n_attempts") if isinstance(agentic.get("n_attempts"), int) else None,
        mean_tool_calls=(
            float(agentic["mean_tool_calls"])
            if isinstance(agentic.get("mean_tool_calls"), (int, float))
            else None
        ),
        mean_turns=(
            float(agentic["mean_turns"])
            if isinstance(agentic.get("mean_turns"), (int, float))
            else None
        ),
        geo_mean_teff_vs_self=(
            float(agentic["geo_mean_teff_vs_self"])
            if isinstance(agentic.get("geo_mean_teff_vs_self"), (int, float))
            else None
        ),
    )


@router.get("/", operation_id="list_models", response_model=list[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model).order_by(Model.name))
    models = list(result.scalars().all())
    out: list[ModelOut] = []
    for m in models:
        eligible = None
        if m.status == ModelStatus.ACTIVE:
            eligible = await model_finalist_eligible(db, m.id)
        out.append(_model_out(m, finalist_eligible=eligible))
    return out


@router.get(
    "/finalist-eligible",
    operation_id="list_finalist_eligible_models",
    response_model=list[ModelOut],
)
async def finalist_eligible_models(db: AsyncSession = Depends(get_db)):
    models = await list_finalist_eligible_models(db)
    return [_model_out(m, finalist_eligible=True) for m in models]


@router.get("/{model_id}", operation_id="get_model_detail", response_model=ModelDetailOut)
async def get_model_detail(model_id: int, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    smoke = await model_has_completed_tier(db, model_id, RunTier.SMOKE)
    standard = await model_has_completed_tier(db, model_id, RunTier.STANDARD)
    thorough = await model_has_completed_tier(db, model_id, RunTier.THOROUGH)
    eligible = standard
    tiers = ModelTierSummary(
        smoke_completed=smoke,
        standard_completed=standard,
        thorough_completed=thorough,
        finalist_eligible=eligible,
    )
    runs_result = await db.execute(
        select(Run)
        .where(Run.model_id == model_id)
        .options(selectinload(Run.results), selectinload(Run.suite))
        .order_by(Run.id.desc())
        .limit(30)
    )
    runs = list(runs_result.scalars().all())
    recent = [_model_run_summary(r) for r in runs]
    last_agentic = None
    for r in runs:
        if not _run_is_finalist(r):
            continue
        agentic = _agentic_from_results(list(r.results or []))
        last_agentic = AgenticMetricsSnippet(
            run_id=r.id,
            n_passed=agentic.get("n_passed") if isinstance(agentic.get("n_passed"), int) else None,
            n_attempts=agentic.get("n_attempts") if isinstance(agentic.get("n_attempts"), int) else None,
            mean_tool_calls=(
                float(agentic["mean_tool_calls"])
                if isinstance(agentic.get("mean_tool_calls"), (int, float))
                else None
            ),
            mean_turns=(
                float(agentic["mean_turns"])
                if isinstance(agentic.get("mean_turns"), (int, float))
                else None
            ),
            geo_mean_teff_vs_self=(
                float(agentic["geo_mean_teff_vs_self"])
                if isinstance(agentic.get("geo_mean_teff_vs_self"), (int, float))
                else None
            ),
            display=agentic.get("display") if isinstance(agentic.get("display"), str) else None,
            suite=agentic.get("suite") if isinstance(agentic.get("suite"), str) else None,
        )
        break
    return ModelDetailOut(
        model=_model_out(model, finalist_eligible=eligible),
        tiers=tiers,
        last_agentic=last_agentic,
        recent_runs=recent,
    )


@router.get(
    "/{model_id}/runs",
    operation_id="list_model_runs",
    response_model=list[ModelRunSummary],
)
async def list_model_runs(
    model_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    runs_result = await db.execute(
        select(Run)
        .where(Run.model_id == model_id)
        .options(selectinload(Run.results), selectinload(Run.suite))
        .order_by(Run.id.desc())
        .limit(limit)
    )
    return [_model_run_summary(r) for r in runs_result.scalars().all()]


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
    if body.notes is not None:
        model.notes = body.notes
    if "context_window" in body.model_fields_set:
        model.context_window = body.context_window
        model.context_window_manual = body.context_window is not None
    if "vram_gb" in body.model_fields_set:
        model.vram_gb = body.vram_gb
    if body.status is not None:
        try:
            model.set_status(ModelStatus(body.status))
        except ValueError as exc:
            raise HTTPException(400, "status must be active|unreachable|archived") from exc
    await db.commit()
    await db.refresh(model)
    eligible = await model_finalist_eligible(db, model.id)
    return _model_out(model, finalist_eligible=eligible)


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
    from benchbase.run_groups import delete_model_and_runs

    return await delete_model_and_runs(db, model_id)


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

    info_map = await client.model_info_map(
        [m.get("id", "") for m in discovered if m.get("id")]
    )

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
        info = info_map.get(name) or {}
        existing = existing_by_lower.get(name.lower())
        if existing:
            if existing.status == ModelStatus.ARCHIVED:
                archived_skipped += 1
                continue
            existing.name = name
            existing.endpoint_url = client.base_url
            _apply_litellm_info(existing, info)
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
            _apply_litellm_info(new_model, info)
            db.add(new_model)
            await db.flush()
            to_ping.append(new_model)
            existing_by_lower[name.lower()] = new_model

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
        info_map = await client.model_info_map(
            [m.get("id", "") for m in discovered if m.get("id")]
        )
    except Exception:
        canonical_ids = {}
        info_map = {}

    details: list[dict] = []
    archived_skipped = 0
    to_ping: list[Model] = []
    for model in all_models:
        if model.status == ModelStatus.ARCHIVED:
            archived_skipped += 1
            continue
        info = info_map.get(model.name)
        if info is None:
            for k, v in info_map.items():
                if k.lower() == model.name.lower():
                    info = v
                    break
        if info:
            _apply_litellm_info(model, info)
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
