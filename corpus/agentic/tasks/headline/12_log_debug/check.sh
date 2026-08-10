#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
text = (root / "config.toml").read_text()
assert 'log_level = "debug"' in text or "log_level = 'debug'" in text, text
print("PASS")
PY
