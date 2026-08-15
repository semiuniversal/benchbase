"""Settings CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from benchbase.config import Settings, load_settings, save_settings

router = APIRouter()


class SettingsOut(BaseModel):
    """Public settings shape — API key is never returned."""

    litellm_base_url: str
    litellm_api_key_set: bool = False
    database_url: str
    theme: str
    default_models: list[str] = Field(default_factory=list)
    benchmark_suites: list[str] = Field(default_factory=list)
    litebench_timeout_seconds: int
    batch_sample_limit: int
    routine_sample_limit: int
    batch_model_concurrency: int
    work_clock_reference_model: str | None = None


class SettingsUpdate(BaseModel):
    litellm_base_url: str | None = Field(
        default=None,
        description="LiteLLM or OpenAI-compatible API base URL.",
    )
    litellm_api_key: str | None = Field(
        default=None,
        description="Bearer token for LiteLLM. Omit or leave blank to keep the saved key.",
    )
    database_url: str | None = Field(
        default=None,
        description="SQLAlchemy database URL (usually unchanged).",
    )
    theme: str | None = Field(default=None, description="UI theme: light or dark.")
    default_models: list[str] | None = Field(
        default=None,
        description="Default model names for batch operations.",
    )
    benchmark_suites: list[str] | None = Field(
        default=None,
        description="Enabled suite runner classes (speed, coding, tool_use, reasoning).",
    )
    litebench_timeout_seconds: int | None = Field(
        default=None,
        description="Per-request timeout for LiteBench coding/tool-use runs.",
    )
    batch_sample_limit: int | None = Field(
        default=None,
        description="Per-task sample limit for Run All batch mode.",
    )
    routine_sample_limit: int | None = Field(
        default=None,
        description="Per-task sample limit for routine single-suite runs.",
    )
    batch_model_concurrency: int | None = Field(
        default=None,
        ge=1,
        le=16,
        description="How many models may run tier axes at once (one axis each).",
    )
    work_clock_reference_model: str | None = Field(
        default=None,
        description="Local Speed-index baseline model. Empty disables the index.",
    )


def settings_to_out(settings: Settings) -> SettingsOut:
    return SettingsOut(
        litellm_base_url=settings.litellm_base_url,
        litellm_api_key_set=bool(settings.litellm_api_key and settings.litellm_api_key.strip()),
        database_url=settings.database_url,
        theme=settings.theme,
        default_models=settings.default_models,
        benchmark_suites=settings.benchmark_suites,
        litebench_timeout_seconds=settings.litebench_timeout_seconds,
        batch_sample_limit=settings.batch_sample_limit,
        routine_sample_limit=settings.routine_sample_limit,
        batch_model_concurrency=settings.batch_model_concurrency,
        work_clock_reference_model=settings.work_clock_reference_model or None,
    )


@router.get(
    "/",
    operation_id="get_settings",
    summary="Get application settings",
    description="Return current settings. The API key is never included; check litellm_api_key_set.",
    response_model=SettingsOut,
)
async def get_settings():
    return settings_to_out(load_settings())


@router.put(
    "/",
    operation_id="update_settings",
    summary="Update application settings",
    description=(
        "Update settings in config/settings.yaml. "
        "Blank litellm_api_key is ignored so the stored key is not wiped."
    ),
    response_model=SettingsOut,
)
async def update_settings(body: SettingsUpdate):
    current = load_settings()
    update_data = body.model_dump(exclude_unset=True)

    # Never wipe a stored key — omit or blank means "keep existing".
    raw_key = update_data.get("litellm_api_key")
    if raw_key is None or not str(raw_key).strip():
        update_data.pop("litellm_api_key", None)
    else:
        update_data["litellm_api_key"] = str(raw_key).strip()

    if "work_clock_reference_model" in update_data:
        raw_ref = update_data.get("work_clock_reference_model")
        update_data["work_clock_reference_model"] = (
            str(raw_ref).strip() if raw_ref and str(raw_ref).strip() else None
        )

    merged = current.model_copy(update=update_data)
    save_settings(merged)
    return settings_to_out(merged)


@router.post(
    "/litellm-probe",
    operation_id="probe_litellm_quality_route",
    summary="Probe LiteLLM quality route",
    description=(
        "Send max_tokens=1 to detect sticky min_tokens on the LiteLLM proxy. "
        "Fails when extra_body forces large min_tokens (poisons quality benchmarks)."
    ),
)
async def probe_litellm_route(
    model: str | None = Query(default=None, description="Model id; default first from /v1/models"),
):
    from benchbase.litellm_probe import probe_litellm_quality_route

    return await probe_litellm_quality_route(model=model)
