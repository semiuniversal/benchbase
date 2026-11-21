"""Creative Arena feature flag (ADR-005)."""

from benchbase.api.routes.creative import _creative_enabled
from benchbase.config import Settings


def test_creative_enabled_via_settings(monkeypatch):
    monkeypatch.delenv("BENCHBASE_CREATIVE_ARENA", raising=False)
    monkeypatch.setattr(
        "benchbase.api.routes.creative.load_settings",
        lambda: Settings(creative_arena_enabled=True),
    )
    assert _creative_enabled() is True


def test_creative_enabled_via_env(monkeypatch):
    monkeypatch.setenv("BENCHBASE_CREATIVE_ARENA", "1")
    monkeypatch.setattr(
        "benchbase.api.routes.creative.load_settings",
        lambda: Settings(creative_arena_enabled=False),
    )
    assert _creative_enabled() is True