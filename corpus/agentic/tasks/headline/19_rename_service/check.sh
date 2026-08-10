#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
text = (root / "config.toml").read_text()
assert 'name = "agentic-svc"' in text or "name = 'agentic-svc'" in text, text
print("PASS")
PY
