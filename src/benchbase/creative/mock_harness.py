"""Mock OpenCode harness for CI (WP7)."""

from __future__ import annotations

import json
from pathlib import Path


def materialize_static_app(workspace: Path, prompt: str) -> dict:
    workspace.mkdir(parents=True, exist_ok=True)
    project = workspace / "project"
    project.mkdir(exist_ok=True)
    index = project / "index.html"
    index.write_text(
        "<!doctype html><html><body><h1>Mock creative app</h1></body></html>",
        encoding="utf-8",
    )
    (workspace / "manifest.json").write_text(
        json.dumps({"prompt_bytes": len(prompt.encode("utf-8")), "harness": "mock"}),
        encoding="utf-8",
    )
    return {"runnable": True, "entry": str(index)}