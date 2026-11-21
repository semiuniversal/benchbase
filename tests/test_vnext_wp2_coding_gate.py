"""WP2/WP4: coding execution disabled by default (ADR-005)."""

from benchbase.config import load_settings


def test_coding_execution_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    s = load_settings()
    assert s.coding_execution_enabled is False