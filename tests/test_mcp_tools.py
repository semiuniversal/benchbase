"""MCP tool catalog and radar-shaper fixtures."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI

from benchbase.mcp_server import RADAR_TOOLS, STATUS_TOOLS, mcp, setup_mcp
from benchbase.radar import shape_radar_chart_data
from benchbase.scoring import QUALITY_AXES


def _dim(primary: float | None, ci_low: float | None = None, ci_high: float | None = None) -> dict:
    return {
        "primary": primary,
        "unit": "%",
        "details": {},
        "ci_low": ci_low,
        "ci_high": ci_high,
        "n_items": 100 if primary is not None else None,
        "planned_n": 100,
        "rank": 1 if primary is not None else None,
    }


SAMPLE_SCORECARD = [
    {
        "model_name": "alpha-27b",
        "model_color": "blue",
        "base_model": "alpha",
        "quant_rank": 2,
        "status": "active",
        "is_active": True,
        "has_benchmark_history": True,
        "best_tier": "standard",
        "borda_score": 40,
        "overall_rank": 1,
        "overall_rank_tied": False,
        "dimensions": {
            axis: _dim(80.0 if axis != "coding" else 37.5, 70.0, 88.0)
            for axis in QUALITY_AXES
        },
    },
    {
        "model_name": "beta-35b",
        "model_color": "teal",
        "base_model": "beta",
        "quant_rank": 3,
        "status": "active",
        "is_active": True,
        "has_benchmark_history": True,
        "best_tier": "standard",
        "borda_score": 32,
        "overall_rank": 2,
        "overall_rank_tied": False,
        "dimensions": {
            axis: _dim(60.0 if axis != "math" else None, 50.0 if axis != "math" else None, 70.0)
            for axis in QUALITY_AXES
        },
    },
    {
        "model_name": "gamma-smoke",
        "model_color": "gray",
        "base_model": "gamma",
        "quant_rank": 1,
        "status": "active",
        "is_active": True,
        "has_benchmark_history": True,
        "best_tier": "smoke",
        "borda_score": 8,
        "overall_rank": 3,
        "dimensions": {axis: _dim(10.0) for axis in QUALITY_AXES},
    },
    {
        "model_name": "archived-one",
        "status": "archived",
        "is_active": False,
        "has_benchmark_history": True,
        "best_tier": "standard",
        "dimensions": {axis: _dim(99.0) for axis in QUALITY_AXES},
    },
]


def test_status_and_radar_tools_registered():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    for required in STATUS_TOOLS + RADAR_TOOLS:
        assert required in names, f"missing MCP tool {required}"
    for extra in (
        "start_batch",
        "list_models",
        "get_settings",
        "get_model_scorecard",
        "arena_chat",
        "get_agentic_current",
    ):
        assert extra in names
    assert "stream_run_log" not in names
    assert "arena_stream" not in names
    assert "stream_agentic_attempt_events" not in names


def test_mcp_mounts_dual_paths():
    app = FastAPI()
    setup_mcp(app)
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/mcp" in paths
    assert "/sse" in paths


def test_mcp_accepts_path_without_trailing_slash():
    from contextlib import asynccontextmanager

    from starlette.testclient import TestClient

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    setup_mcp(app)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json=payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200
    assert b"BenchBase" in response.content or "tools" in response.text


def test_radar_shaper_golden_fixture():
    payload = shape_radar_chart_data(SAMPLE_SCORECARD)
    assert payload["axis_keys"] == list(QUALITY_AXES)
    assert len(payload["axes"]) == 8
    names = {s["model_name"] for s in payload["series"]}
    assert names == {"alpha-27b", "beta-35b"}
    knowledge = next(a for a in payload["axes"] if a["key"] == "knowledge")
    assert knowledge["scores"]["alpha-27b"]["raw"] == 80.0
    assert knowledge["scores"]["alpha-27b"]["ci_low"] == 70.0
    assert knowledge["scores"]["alpha-27b"]["ci_high"] == 88.0
    assert knowledge["scores"]["beta-35b"]["value"] == 60.0
    math_axis = next(a for a in payload["axes"] if a["key"] == "math")
    assert math_axis["scores"]["beta-35b"]["value"] is None
    coding = next(a for a in payload["axes"] if a["key"] == "coding")
    assert coding["scores"]["alpha-27b"]["raw"] == 37.5
    row = payload["radar_data"][0]
    assert row["_axisKey"] == "knowledge"
    assert row["alpha-27b"] == 80.0


def test_radar_stretch_and_family_filter():
    stretched = shape_radar_chart_data(SAMPLE_SCORECARD, stretch=True, show_smoke=True)
    knowledge = next(a for a in stretched["axes"] if a["key"] == "knowledge")
    # smoke 10 and alpha 80 span → alpha near 100, smoke near 0
    assert knowledge["scores"]["alpha-27b"]["value"] == 100.0
    assert knowledge["scores"]["gamma-smoke"]["value"] == 0.0
    family = shape_radar_chart_data(
        SAMPLE_SCORECARD
        + [
            {
                "model_name": "alpha-q8",
                "base_model": "alpha",
                "quant_rank": 8,
                "status": "active",
                "is_active": True,
                "has_benchmark_history": True,
                "best_tier": "standard",
                "dimensions": {axis: _dim(90.0) for axis in QUALITY_AXES},
            }
        ],
        group_by_family=True,
    )
    names = [s["model_name"] for s in family["series"]]
    assert "alpha-q8" in names
    assert "alpha-27b" not in names
