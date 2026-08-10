#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
cl = root / "CHANGELOG.md"
assert cl.exists() and "greet" in cl.read_text().lower(), cl
print("PASS")
PY
