#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
root = Path(os.environ["AGENTIC_WORKSPACE"])
spec = spec_from_file_location("greet", root / "src" / "greet.py")
mod = module_from_spec(spec)
spec.loader.exec_module(mod)
assert "Welcome" in mod.greet("Ada"), mod.greet("Ada")
print("PASS")
PY
