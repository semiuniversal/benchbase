#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
marker = root / "ABSTAINED"
if not marker.exists():
    raise SystemExit("missing ABSTAINED")
print("PASS")
PY
