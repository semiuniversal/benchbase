"""Placeholder upstream adapters (WP6); listed only when flag enabled."""

from __future__ import annotations

from typing import Any

from benchbase.adapters.base import AdapterCapabilities, BenchmarkAdapter


class AIPerfAdapterStub(BenchmarkAdapter):
    """AIPerf headless load-test hook — execution blocked until WP6 qualification."""

    protocol_id = "aiperf.headless.v0"
    protocol_version = "0"
    upstream_pin = "TBD"
    capabilities = AdapterCapabilities(needs_sandbox=False)

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "AIPerf adapter is registered for discovery only; enable after pin and isolation review."
        )