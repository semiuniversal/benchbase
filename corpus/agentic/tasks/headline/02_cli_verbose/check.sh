#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os, re
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
src = (root / "src" / "cli.py").read_text()
assert re.search(r"add_argument\([^)]*verbose", src), src
print("PASS")
PY
