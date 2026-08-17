"""Official mcp v2 server: dual-era Streamable HTTP at /mcp plus legacy SSE at /sse."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from benchbase.db.models import Run, RunStatus
from benchbase.db.session import get_session_factory

mcp = MCPServer(
    "BenchBase",
    instructions=(
        "Local LLM benchmark dashboard. Poll get_batch_status and list_active_runs "
        "for live progress (no long-lived SSE tools). Pass run_id / run_group_id as "
        "handles — protocol sessions do not store application state. "
        "get_radar_chart_data returns plot-ready eight-axis scores with Wilson CIs."
    ),
)

STATUS_TOOLS = (
    "get_batch_status",
    "list_active_runs",
    "get_run",
    "get_run_timing",
    "get_run_log_history",
)

RADAR_TOOLS = ("get_radar_chart_data",)


def _dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    return value


async def _invoke(handler, **kwargs: Any) -> Any:
    try:
        result = await handler(**kwargs)
        return _dump(result)
    except HTTPException as exc:
        return {"error": True, "status_code": exc.status_code, "detail": exc.detail}


async def _with_db(handler, **kwargs: Any) -> Any:
    factory = get_session_factory()
    async with factory() as db:
        return await _invoke(handler, db=db, **kwargs)


def _transport_kwargs() -> dict[str, Any]:
    # LAN dashboard (no auth). Disable localhost-only DNS-rebinding allowlist.
    return {"host": "0.0.0.0"}


_streamable_app = None
_sse_app = None


def setup_mcp(app: FastAPI) -> MCPServer:
    """Mount dual-era Streamable HTTP at /mcp and legacy HTTP+SSE at /sse."""
    global _streamable_app, _sse_app
    if _streamable_app is None:
        _streamable_app = mcp.streamable_http_app(streamable_http_path="/", **_transport_kwargs())
    if _sse_app is None:
        _sse_app = mcp.sse_app(sse_path="/", message_path="/message", **_transport_kwargs())
    app.mount("/mcp", _streamable_app)
    app.mount("/sse", _sse_app)
    return mcp


# --- Status ---


@mcp.tool()
async def get_batch_status() -> dict[str, Any]:
    """Live batch queue: idle/running/paused/pausing, pending_count, current_runs with timing.

    Poll this instead of run-log SSE. current_runs include label, run_id, model, and
    optional timing (elapsed, ETA, progress). Application state is in SQLite, not MCP sessions.
    """
    from benchbase.api.routes.benchmarks import batch_status, get_run_timing

    status = await batch_status()
    currents = list(status.get("current_runs") or [])
    if not currents:
        return status
    factory = get_session_factory()
    async with factory() as db:
        enriched = []
        for current in currents:
            timing = await _invoke(get_run_timing, run_id=current["run_id"], db=db)
            row = dict(current)
            row["timing"] = None if isinstance(timing, dict) and timing.get("error") else timing
            enriched.append(row)
        out = dict(status)
        out["current_runs"] = enriched
        return out


@mcp.tool()
async def list_active_runs() -> dict[str, Any]:
    """All pending, running, pausing, and paused runs with suite, group, and tier."""
    from benchbase.api.routes.benchmarks import _effective_run_status, _run_to_out

    factory = get_session_factory()
    async with factory() as db:
        stmt = (
            select(Run)
            .options(
                selectinload(Run.results),
                selectinload(Run.suite),
                selectinload(Run.model),
            )
            .where(Run.status.in_([RunStatus.PENDING, RunStatus.RUNNING, RunStatus.PAUSED]))
            .order_by(Run.id.desc())
        )
        runs = (await db.execute(stmt)).scalars().all()
        out = []
        for run in runs:
            payload = _run_to_out(run, run.results).model_dump(mode="json")
            suite = run.suite
            model = run.model
            payload["suite_name"] = suite.name if suite else None
            payload["suite_axis"] = suite.axis.value if suite and getattr(suite, "axis", None) else None
            payload["model_name"] = model.name if model else None
            payload["effective_status"] = _effective_run_status(run)
            out.append(payload)
        return {"runs": out, "count": len(out)}


@mcp.tool()
async def get_run(run_id: int) -> Any:
    """Fetch one benchmark run by ID, including per-task result summaries."""
    from benchbase.api.routes.benchmarks import get_run as get_run_route

    return await _with_db(get_run_route, run_id=run_id)


@mcp.tool()
async def get_run_timing(run_id: int) -> Any:
    """Elapsed time, static estimate, and live ETA when progress is visible in logs."""
    from benchbase.api.routes.benchmarks import get_run_timing as get_run_timing_route

    return await _with_db(get_run_timing_route, run_id=run_id)


@mcp.tool()
async def get_run_log_history(run_id: int) -> Any:
    """Persisted run log as JSON lines. Use this instead of stream_run_log SSE."""
    from benchbase.api.routes.benchmarks import get_run_log_history as get_run_log_history_route

    return await _with_db(get_run_log_history_route, run_id=run_id)


# --- Benchmarks ---


@mcp.tool()
async def start_batch(
    model_id: int,
    tier: Literal["smoke", "standard", "thorough"] = "standard",
    smoke_override: bool = False,
) -> Any:
    """Queue a full Smoke/Standard/Thorough tier for one active model."""
    from benchbase.api.routes.benchmarks import BatchStart, batch_start

    return await _invoke(
        batch_start, body=BatchStart(model_id=model_id, tier=tier, smoke_override=smoke_override)
    )


@mcp.tool()
async def cancel_batch() -> Any:
    """Abort and discard the active tier set (all axes)."""
    from benchbase.api.routes.benchmarks import batch_cancel

    return await _with_db(batch_cancel)


@mcp.tool()
async def create_run(
    model_id: int,
    suite_id: int,
    eval_mode: Literal["routine", "full"] = "routine",
) -> Any:
    """Queue a new run for a model and suite. Does not start execution; call start_run."""
    from benchbase.api.routes.benchmarks import RunCreate, create_run as create_run_route

    return await _with_db(
        create_run_route,
        body=RunCreate(model_id=model_id, suite_id=suite_id, eval_mode=eval_mode),
    )


@mcp.tool()
async def list_runs(model_id: int | None = None, limit: int = 200) -> Any:
    """Recent benchmark runs with result summaries (newest first)."""
    from benchbase.api.routes.benchmarks import list_runs as list_runs_route

    return await _with_db(list_runs_route, model_id=model_id, limit=limit)


@mcp.tool()
async def start_run(run_id: int) -> Any:
    """Begin execution of a pending run using the suite's registered runner."""
    from benchbase.api.routes.benchmarks import start_run as start_run_route

    return await _with_db(start_run_route, run_id=run_id)


@mcp.tool()
async def pause_run(run_id: int) -> Any:
    """Cooperative pause between items. Checkpointed progress is kept."""
    from benchbase.api.routes.benchmarks import pause_run_route

    return await _with_db(pause_run_route, run_id=run_id)


@mcp.tool()
async def resume_run(run_id: int) -> Any:
    """Resume a paused benchmark. Already-scored items are skipped."""
    from benchbase.api.routes.benchmarks import resume_run_route

    return await _with_db(resume_run_route, run_id=run_id)


@mcp.tool()
async def pause_run_group(run_group_id: str) -> Any:
    """Pause the running member of a Smoke/Standard/Thorough set."""
    from benchbase.api.routes.benchmarks import pause_run_group_route

    return await _with_db(pause_run_group_route, run_group_id=run_group_id)


@mcp.tool()
async def resume_run_group(run_group_id: str) -> Any:
    """Resume a paused tier set."""
    from benchbase.api.routes.benchmarks import resume_run_group_route

    return await _with_db(resume_run_group_route, run_group_id=run_group_id)


@mcp.tool()
async def abort_run_group(run_group_id: str) -> Any:
    """Stop and discard a tier run set so partial results never enter the scorecard."""
    from benchbase.api.routes.benchmarks import abort_run_group_route

    return await _with_db(abort_run_group_route, run_group_id=run_group_id)


@mcp.tool()
async def estimate_duration(suite_id: int, eval_mode: str = "routine") -> Any:
    """Preview rough duration before launching a run for a suite and eval mode."""
    from benchbase.api.routes.benchmarks import estimate_benchmark

    return await _with_db(estimate_benchmark, suite_id=suite_id, eval_mode=eval_mode)


@mcp.tool()
async def list_suites() -> Any:
    """Registered benchmark suites (v2 quality axes + speed + smoke + agentic)."""
    from benchbase.api.routes.benchmarks import list_suites as list_suites_route

    return await _with_db(list_suites_route)


@mcp.tool()
async def run_controls(tier: str = "standard") -> Any:
    """Run null/random/echo scoring controls for the given tier."""
    from benchbase.api.routes.benchmarks import run_scoring_controls

    return await _with_db(run_scoring_controls, tier=tier)


@mcp.tool()
async def controls_status() -> Any:
    """Scorer validity status from control bounds."""
    from benchbase.api.routes.benchmarks import scoring_controls_status

    return await _with_db(scoring_controls_status)


@mcp.tool()
async def start_agentic(
    model_id: int,
    suite_version: Literal["mvp", "headline"] = "mvp",
    n_seeds: int | None = None,
    mock: bool = False,
    instrument_validation: bool = False,
) -> Any:
    """Start Finalist · Agentic (not Smoke/Standard/Thorough). Requires sole tenancy."""
    from benchbase.api.routes.benchmarks import AgenticStart, start_agentic as start_agentic_route

    return await _with_db(
        start_agentic_route,
        body=AgenticStart(
            model_id=model_id,
            suite_version=suite_version,
            n_seeds=n_seeds,
            mock=mock,
            instrument_validation=instrument_validation,
        ),
    )


# --- Models ---


@mcp.tool()
async def list_models() -> Any:
    """List registered models (active, unreachable, archived)."""
    from benchbase.api.routes.models import list_models as list_models_route

    return await _with_db(list_models_route)


@mcp.tool()
async def get_model(model_id: int) -> Any:
    """Model detail: registry fields, tier summary, recent runs, last agentic snippet."""
    from benchbase.api.routes.models import get_model_detail

    return await _with_db(get_model_detail, model_id=model_id)


@mcp.tool()
async def add_model(
    name: str,
    endpoint_url: str,
    backend_runtime: str | None = None,
    quantization: str | None = None,
    host: str | None = None,
) -> Any:
    """Register a LiteLLM-connected model."""
    from benchbase.api.routes.models import ModelCreate, add_model as add_model_route

    return await _with_db(
        add_model_route,
        body=ModelCreate(
            name=name,
            endpoint_url=endpoint_url,
            backend_runtime=backend_runtime,
            quantization=quantization,
            host=host,
        ),
    )


@mcp.tool()
async def update_model(
    model_id: int,
    color: str | None = None,
    notes: str | None = None,
    context_window: int | None = None,
    vram_gb: float | None = None,
    status: str | None = None,
    base_model: str | None = None,
    quant_rank: int | None = None,
) -> Any:
    """Update model metadata (color, notes, context window, VRAM, status)."""
    from benchbase.api.routes.models import ModelUpdate, update_model as update_model_route

    payload = {
        k: v
        for k, v in {
            "color": color,
            "notes": notes,
            "context_window": context_window,
            "vram_gb": vram_gb,
            "status": status,
            "base_model": base_model,
            "quant_rank": quant_rank,
        }.items()
        if v is not None
    }
    return await _with_db(update_model_route, model_id=model_id, body=ModelUpdate(**payload))


@mcp.tool()
async def archive_model(model_id: int) -> Any:
    """Archive a model (hidden from Compare; kept in the registry)."""
    from benchbase.api.routes.models import archive_model as archive_model_route

    return await _with_db(archive_model_route, model_id=model_id)


@mcp.tool()
async def unarchive_model(model_id: int) -> Any:
    """Unarchive a model."""
    from benchbase.api.routes.models import unarchive_model as unarchive_model_route

    return await _with_db(unarchive_model_route, model_id=model_id)


@mcp.tool()
async def bulk_archive(model_ids: list[int]) -> Any:
    """Archive several models at once."""
    from benchbase.api.routes.models import BulkArchiveBody, bulk_archive as bulk_archive_route

    return await _with_db(bulk_archive_route, body=BulkArchiveBody(model_ids=model_ids))


@mcp.tool()
async def delete_model(model_id: int) -> Any:
    """Delete a model and its runs."""
    from benchbase.api.routes.models import delete_model as delete_model_route

    return await _with_db(delete_model_route, model_id=model_id)


@mcp.tool()
async def discover_models() -> Any:
    """Discover models from LiteLLM and upsert the registry."""
    from benchbase.api.routes.models import discover_models as discover_models_route

    return await _with_db(discover_models_route)


@mcp.tool()
async def recheck_models() -> Any:
    """Re-check health of registered models against LiteLLM."""
    from benchbase.api.routes.models import recheck_models as recheck_models_route

    return await _with_db(recheck_models_route)


@mcp.tool()
async def list_model_runs(model_id: int, limit: int = 50) -> Any:
    """Recent runs for one model."""
    from benchbase.api.routes.models import list_model_runs as list_model_runs_route

    return await _with_db(list_model_runs_route, model_id=model_id, limit=limit)


@mcp.tool()
async def list_finalist_eligible() -> Any:
    """Models eligible for Finalist · Agentic (completed Standard or Thorough)."""
    from benchbase.api.routes.models import finalist_eligible_models

    return await _with_db(finalist_eligible_models)


# --- Settings ---


@mcp.tool()
async def get_settings() -> Any:
    """Current settings. The API key is never included; check litellm_api_key_set."""
    from benchbase.api.routes.settings import get_settings as get_settings_route

    return await _invoke(get_settings_route)


@mcp.tool()
async def update_settings(
    litellm_base_url: str | None = None,
    litellm_api_key: str | None = None,
    theme: str | None = None,
    batch_sample_limit: int | None = None,
    routine_sample_limit: int | None = None,
    batch_model_concurrency: int | None = None,
    work_clock_reference_model: str | None = None,
    litebench_timeout_seconds: int | None = None,
) -> Any:
    """Update settings in config/settings.yaml. Blank litellm_api_key keeps the stored key."""
    from benchbase.api.routes.settings import SettingsUpdate, update_settings as update_settings_route

    payload = {
        k: v
        for k, v in {
            "litellm_base_url": litellm_base_url,
            "litellm_api_key": litellm_api_key,
            "theme": theme,
            "batch_sample_limit": batch_sample_limit,
            "routine_sample_limit": routine_sample_limit,
            "batch_model_concurrency": batch_model_concurrency,
            "work_clock_reference_model": work_clock_reference_model,
            "litebench_timeout_seconds": litebench_timeout_seconds,
        }.items()
        if v is not None
    }
    return await _invoke(update_settings_route, body=SettingsUpdate(**payload))


@mcp.tool()
async def probe_litellm(model: str | None = None) -> Any:
    """Probe LiteLLM quality route (max_tokens=1) for sticky min_tokens."""
    from benchbase.api.routes.settings import probe_litellm_route

    return await _invoke(probe_litellm_route, model=model)


# --- Results / board ---


@mcp.tool()
async def get_model_scorecard() -> Any:
    """Ranked scorecard for all models with benchmark history (eight quality axes + speed)."""
    from benchbase.api.routes.results import model_scorecard

    return await _with_db(model_scorecard)


@mcp.tool()
async def get_scorecard(run_ids: list[int]) -> Any:
    """Ranked scorecard comparing models across dimensions for specific run IDs."""
    from benchbase.api.routes.results import scorecard

    return await _with_db(scorecard, run_ids=run_ids)


@mcp.tool()
async def compare_runs(run_ids: list[int]) -> Any:
    """Compare task scores across multiple runs by run ID."""
    from benchbase.api.routes.results import compare_runs as compare_runs_route

    return await _with_db(compare_runs_route, run_ids=run_ids)


@mcp.tool()
async def get_results_by_run(run_id: int) -> Any:
    """All scored task results for a single benchmark run."""
    from benchbase.api.routes.results import results_for_run

    return await _with_db(results_for_run, run_id=run_id)


@mcp.tool()
async def get_radar_chart_data(
    model_names: list[str] | None = None,
    stretch: bool = False,
    group_by_family: bool = False,
    active_only: bool = False,
    show_smoke: bool = False,
    show_unbenchmarked: bool = False,
) -> dict[str, Any]:
    """Plot-ready radar: eight quality axes, per-model scores, Wilson CI (ci_low/ci_high).

    Mirrors the Compare page radar. Poll get_model_scorecard for the raw table.
    """
    from benchbase.api.routes.results import model_scorecard
    from benchbase.radar import shape_radar_chart_data

    entries = await _with_db(model_scorecard)
    if isinstance(entries, dict) and entries.get("error"):
        return entries
    return shape_radar_chart_data(
        list(entries),
        model_names=model_names,
        stretch=stretch,
        group_by_family=group_by_family,
        active_only=active_only,
        show_smoke=show_smoke,
        show_unbenchmarked=show_unbenchmarked,
    )


# --- Arena ---


@mcp.tool()
async def arena_chat(
    prompt: str,
    models: list[str],
    max_tokens: int | None = None,
    temperature: float = 0.7,
) -> Any:
    """Send the same prompt to multiple models; JSON responses (not SSE)."""
    from benchbase.api.routes.arena import ArenaRequest, arena_chat as arena_chat_route

    return await _with_db(
        arena_chat_route,
        body=ArenaRequest(prompt=prompt, models=models, max_tokens=max_tokens, temperature=temperature),
    )


# --- Agentic inspect ---


@mcp.tool()
async def get_agentic_current(run_id: int) -> Any:
    """Current agentic attempt pointer for a run."""
    from benchbase.api.routes.benchmarks import agentic_current

    return await _with_db(agentic_current, run_id=run_id)


@mcp.tool()
async def list_agentic_attempts(run_id: int) -> Any:
    """List agentic attempts for a run (no event SSE)."""
    from benchbase.api.routes.benchmarks import list_agentic_attempts as list_agentic_attempts_route

    return await _with_db(list_agentic_attempts_route, run_id=run_id)


@mcp.tool()
async def get_agentic_transcript(run_id: int, item_id: str) -> Any:
    """Normalized agentic attempt transcript. item_id looks like task:seedN."""
    from benchbase.api.routes.benchmarks import get_agentic_transcript as get_agentic_transcript_route

    return await _with_db(get_agentic_transcript_route, run_id=run_id, item_id=item_id)


@mcp.tool()
async def get_agentic_workspace(run_id: int, item_id: str) -> Any:
    """Fixture workspace tree for an agentic attempt."""
    from benchbase.api.routes.benchmarks import get_agentic_workspace as get_agentic_workspace_route

    return await _with_db(get_agentic_workspace_route, run_id=run_id, item_id=item_id)


@mcp.tool()
async def get_agentic_workspace_file(run_id: int, item_id: str, path: str) -> Any:
    """Read a fixture file from an agentic attempt workspace."""
    from benchbase.api.routes.benchmarks import get_agentic_workspace_file as get_file_route

    return await _with_db(get_file_route, run_id=run_id, item_id=item_id, path=path)
