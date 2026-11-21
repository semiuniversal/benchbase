"""Benchmark adapter contract (vNext WP6)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdapterCapabilities:
    needs_logprobs: bool = False
    needs_tools: bool = False
    needs_sandbox: bool = False
    needs_schema_enforcement: bool = False


@dataclass
class AdapterProgress:
    planned: int = 0
    attempted: int = 0
    completed: int = 0
    scorable: int = 0


class BenchmarkAdapter(ABC):
    protocol_id: str
    protocol_version: str
    upstream_pin: str | None = None
    capabilities: AdapterCapabilities = field(default_factory=AdapterCapabilities)

    @abstractmethod
    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Execute protocol; return normalized result dict."""