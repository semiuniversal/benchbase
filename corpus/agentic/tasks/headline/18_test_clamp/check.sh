#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
t = root / "tests" / "test_clamp.py"
assert t.exists() and "clamp_index" in t.read_text(), t
print("PASS")
PY
