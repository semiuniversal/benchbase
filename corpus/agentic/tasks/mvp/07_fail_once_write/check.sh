#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
out = root / "out.txt"
assert out.exists() and out.read_text().strip() == "recovered", out
assert not (root / ".fail_once_lock").exists()
print("PASS")
PY
