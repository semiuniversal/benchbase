#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os, sys
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
sys.path.insert(0, str(root))
from src import mathutil
assert hasattr(mathutil, "sub") and mathutil.sub(5, 2) == 3
print("PASS")
PY
