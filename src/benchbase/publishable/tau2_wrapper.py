"""τ² (tau2-bench) verbatim wrapper — attach operational ledger only."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from benchbase.publishable import LedgerTimer, OperationalLedger


def run_tau2_with_ledger(
    *,
    suite_name: str,
    command: list[str] | None = None,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    package_hash: str = "placeholder-until-estimator-store",
    litellm_profile: str | None = None,
    sidecar_path: Path | str | None = None,
    native_metrics: dict[str, Any] | None = None,
) -> OperationalLedger:
    """Run τ² verbatim when installed; always emit ledger side-car JSON."""
    cmd = command or ["tau2", "--help"]
    timer = LedgerTimer()
    success: bool | None = None
    stdout = ""
    stderr = ""
    with timer:
        if shutil.which(cmd[0]) is None and command is None:
            success = None
            stderr = "tau2 binary not found on PATH — ledger-only stub"
        else:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                env={**os.environ, **(env or {})},
                capture_output=True,
                text=True,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            success = proc.returncode == 0

    metrics = dict(native_metrics or {})
    if stdout:
        metrics["stdout_tail"] = stdout[-4000:]
    if stderr:
        metrics["stderr_tail"] = stderr[-2000:]

    ledger = OperationalLedger(
        suite_engine="tau2",
        suite_name=suite_name,
        wall_seconds=timer.elapsed,
        success=success,
        native_metrics=metrics,
        package_hash=package_hash,
        litellm_profile=litellm_profile,
        harness_version=os.environ.get("TAU2_VERSION"),
    )
    p = metrics.get("p_success")
    if isinstance(p, (int, float)):
        ledger.derive_teff(p_success=float(p))
    elif success is not None:
        ledger.derive_teff()

    out = Path(sidecar_path) if sidecar_path else Path("tau2_ledger.json")
    ledger.write_json(out)
    return ledger


def parse_tau2_results_json(path: Path | str) -> dict[str, Any]:
    """Best-effort extract of native τ² metrics from a results JSON file."""
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    return {"raw": data}
