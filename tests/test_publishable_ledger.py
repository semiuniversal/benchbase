"""Phase B ledger wrapper smoke tests (no Harbor/τ² install required)."""

from __future__ import annotations

from pathlib import Path

from benchbase.publishable.harbor_wrapper import run_harbor_with_ledger
from benchbase.publishable.tau2_wrapper import run_tau2_with_ledger


def test_harbor_ledger_sidecar(tmp_path: Path):
    out = tmp_path / "harbor_ledger.json"
    ledger = run_harbor_with_ledger(
        suite_name="stub",
        sidecar_path=out,
        native_metrics={"p_success": 0.5},
    )
    assert out.exists()
    assert ledger.suite_engine == "harbor"
    assert ledger.t_eff is not None


def test_tau2_ledger_sidecar(tmp_path: Path):
    out = tmp_path / "tau2_ledger.json"
    ledger = run_tau2_with_ledger(suite_name="stub", sidecar_path=out)
    assert out.exists()
    assert ledger.suite_engine == "tau2"
