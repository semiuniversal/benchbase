"""OpenCode integration — live when BENCHBASE_OPENCODE_LIVE=1, else mock (WP7)."""

from __future__ import annotations

import os
from pathlib import Path

PINNED_OPENCODE_VERSION = "1.0.80"


async def run_attempt(*, workspace: str, prompt: str, endpoint_url: str) -> dict:
    """Run creative attempt in workspace; never executes on API host."""
    root = Path(workspace)
    if os.environ.get("BENCHBASE_OPENCODE_LIVE", "").lower() not in ("1", "true", "yes"):
        from benchbase.creative.mock_harness import materialize_static_app

        out = materialize_static_app(root, prompt)
        return {
            "harness": "mock",
            "opencode_version": PINNED_OPENCODE_VERSION,
            "endpoint_url": endpoint_url,
            **out,
        }
    raise NotImplementedError(
        "Set BENCHBASE_OPENCODE_LIVE=1 only after worker compose pin is verified"
    )