#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
t = (root / "health_ok.txt").read_text().strip().lower()
assert t == "true", t
print("PASS")
PY
