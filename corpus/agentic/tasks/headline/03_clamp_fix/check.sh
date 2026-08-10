#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os, sys
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
sys.path.insert(0, str(root))
from src.mathutil import clamp_index
assert clamp_index(5, 5) == 4, clamp_index(5, 5)
assert clamp_index(4, 5) == 4
assert clamp_index(0, 5) == 0
assert clamp_index(-1, 5) == 0
print("PASS")
PY
