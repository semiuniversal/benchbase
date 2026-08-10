#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os, sys
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
sys.path.insert(0, str(root))
from app.server import create_app
r = create_app().handle("GET", "/echo")
assert r.body.get("message") == "pong", r.body
print("PASS")
PY
