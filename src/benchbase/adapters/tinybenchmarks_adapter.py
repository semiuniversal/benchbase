"""tinyBenchmarks protocol adapter (WP6) — offline golden validation only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchbase.adapters.base import AdapterCapabilities, BenchmarkAdapter

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "tests" / "fixtures" / "tinybenchmarks_golden.json"


class TinyBenchmarksAdapter(BenchmarkAdapter):
    protocol_id = "tinybenchmarks"
    protocol_version = "felipemaiapolo/tinyBenchmarks@v0.1"
    upstream_pin = "https://github.com/felipemaiapolo/tinyBenchmarks"
    capabilities = AdapterCapabilities(needs_logprobs=False, needs_sandbox=False)

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        if not GOLDEN.is_file():
            return {
                "status": "unavailable",
                "reason": "golden fixture missing",
                "protocol_id": self.protocol_id,
            }
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        suite = context.get("suite") or golden.get("default_suite")
        expected = golden.get("suites", {}).get(suite)
        if expected is None:
            return {"status": "error", "reason": f"unknown suite {suite!r}"}
        return {
            "status": "ok",
            "protocol_id": self.protocol_id,
            "protocol_version": self.protocol_version,
            "suite": suite,
            "expected_score": expected.get("score"),
            "item_count": expected.get("n"),
            "offline": True,
        }