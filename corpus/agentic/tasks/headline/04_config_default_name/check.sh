#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
text = (root / "config.toml").read_text()
assert 'default_name = "friend"' in text or "default_name = 'friend'" in text, text
print("PASS")
PY
