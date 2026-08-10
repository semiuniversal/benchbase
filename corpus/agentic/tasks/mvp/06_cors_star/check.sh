#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
cfg_text = (root / "config.toml").read_text()
cfg_py = (root / "app" / "config.py").read_text()
ok = 'cors_origin = "*"' in cfg_text or "cors_origin = '*'" in cfg_text
ok = ok or 'cors_origin: str = "*"' in cfg_py or "cors_origin: str = '*'" in cfg_py
assert ok, (cfg_text, cfg_py)
print("PASS")
PY
