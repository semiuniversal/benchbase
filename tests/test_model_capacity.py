"""Context window + VRAM capacity facts on models and the scorecard."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from benchbase.api.routes.models import ModelUpdate, _apply_litellm_info, update_model
from benchbase.db.models import Base, Model, ModelStatus
from benchbase.scoring import _build_scorecards, compute_model_scorecard


def test_apply_litellm_info_fills_empty_context():
    model = Model(name="seat-a", endpoint_url="http://127.0.0.1:9", color="blue")
    _apply_litellm_info(model, {"context_window": 131072, "supports_vision": False})
    assert model.context_window == 131072
    assert not bool(model.context_window_manual)


def test_apply_litellm_info_skips_manual_context():
    model = Model(name="seat-a", endpoint_url="http://127.0.0.1:9", color="blue")
    model.context_window = 8192
    model.context_window_manual = True
    _apply_litellm_info(model, {"context_window": 131072, "supports_vision": False})
    assert model.context_window == 8192


def test_apply_litellm_info_overwrites_discovered_context():
    model = Model(name="seat-a", endpoint_url="http://127.0.0.1:9", color="blue")
    model.context_window = 8192
    model.context_window_manual = False
    _apply_litellm_info(model, {"context_window": 131072, "supports_vision": False})
    assert model.context_window == 131072


def test_scorecard_includes_capacity():
    cards = _build_scorecards(
        {
            "seat-a": {
                "model_name": "seat-a",
                "model_color": "blue",
                "base_model": "seat",
                "quant_rank": 1,
                "status": "active",
                "is_active": True,
                "has_benchmark_history": False,
                "context_window": 131072,
                "vram_gb": 24.0,
                "suite_versions": {},
                "all_results": [],
                "axis_runs": {},
            }
        },
        {},
        {},
    )
    assert cards[0]["context_window"] == 131072
    assert cards[0]["vram_gb"] == 24.0


async def _capacity_db(db_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        model = Model(
            name="seat-a",
            endpoint_url="http://127.0.0.1:9",
            color="blue",
        )
        model.set_status(ModelStatus.ACTIVE)
        db.add(model)
        await db.commit()
        await db.refresh(model)

        out = await update_model(
            model.id,
            ModelUpdate(context_window=32768, vram_gb=18.5),
            db,
        )
        assert out.context_window == 32768
        assert out.context_window_manual is True
        assert out.vram_gb == 18.5

        await db.refresh(model)
        _apply_litellm_info(model, {"context_window": 131072})
        assert model.context_window == 32768

        cleared = await update_model(
            model.id,
            ModelUpdate(context_window=None, vram_gb=None),
            db,
        )
        assert cleared.context_window is None
        assert cleared.context_window_manual is False
        assert cleared.vram_gb is None

        cards = await compute_model_scorecard(db)
        by_name = {c["model_name"]: c for c in cards}
        assert by_name["seat-a"]["context_window"] is None
        assert by_name["seat-a"]["vram_gb"] is None

        filled = await update_model(
            model.id,
            ModelUpdate(context_window=131072, vram_gb=24),
            db,
        )
        assert filled.context_window == 131072
        cards = await compute_model_scorecard(db)
        by_name = {c["model_name"]: c for c in cards}
        assert by_name["seat-a"]["context_window"] == 131072
        assert by_name["seat-a"]["vram_gb"] == 24.0


def test_patch_set_and_clear_capacity_and_scorecard():
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_capacity_db(Path(tmp) / "cap.db"))
