"""Harbor / EvoCode verbatim wrapper — attach operational ledger only.

Does not reimplement Harbor inside OMP. Invoke the native Harbor CLI/runner
when installed; otherwise raise a clear error. Ledger side-car is always written.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from benchbase.publishable import LedgerTimer, OperationalLedger


def run_harbor_with_ledger(
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
    """Run Harbor verbatim (or dry-run parse) and write ledger side-car JSON."""
    cmd = command or ["harbor", "--help"]
    harbor_bin = shutil.which(cmd[0]) if cmd else None
    timer = LedgerTimer()
    success: bool | None = None
    stdout = ""
    stderr = ""
    with timer:
        if harbor_bin is None and command is None:
            # Documented dry path when Harbor is not installed on this host.
            success = None
            stderr = "harbor binary not found on PATH — ledger-only stub"
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
        suite_engine="harbor",
        suite_name=suite_name,
        wall_seconds=timer.elapsed,
        success=success,
        native_metrics=metrics,
        package_hash=package_hash,
        litellm_profile=litellm_profile,
        harness_version=os.environ.get("HARBOR_VERSION"),
    )
    # If caller provided success rate in native_metrics, derive T_eff.
    p = metrics.get("p_success")
    if isinstance(p, (int, float)):
        ledger.derive_teff(p_success=float(p))
    elif success is not None:
        ledger.derive_teff()

    out = Path(sidecar_path) if sidecar_path else Path("harbor_ledger.json")
    ledger.write_json(out)
    return ledger


def load_native_metrics_json(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
