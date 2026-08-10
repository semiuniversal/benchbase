#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os, sys
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
sys.path.insert(0, str(root))
from src.greet import shout
assert shout("Ada") == "WELCOME, ADA!", shout("Ada")
print("PASS")
PY
