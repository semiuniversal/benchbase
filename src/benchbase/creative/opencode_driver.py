"""OpenCode integration stub — pin version at deploy time (WP7)."""

from __future__ import annotations

PINNED_OPENCODE_VERSION = "0.0.0-placeholder"


async def run_attempt(*, workspace: str, prompt: str, endpoint_url: str) -> dict:
    raise NotImplementedError(
        "OpenCode live integration requires owner-approved short test; use mock_harness in CI"
    )