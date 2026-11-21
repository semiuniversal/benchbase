from __future__ import annotations

from typing import Any

from benchbase.adapters.base import BenchmarkAdapter
from benchbase.adapters.stubs import AIPerfAdapterStub
from benchbase.config import Settings, load_settings

_REGISTRY: dict[str, BenchmarkAdapter] = {}


def register_adapter(adapter: BenchmarkAdapter) -> None:
    _REGISTRY[adapter.protocol_id] = adapter


def get_adapter(protocol_id: str) -> BenchmarkAdapter | None:
    return _REGISTRY.get(protocol_id)


def _bootstrap_registry() -> None:
    if _REGISTRY:
        return
    register_adapter(AIPerfAdapterStub())


def adapter_descriptors(settings: Settings | None = None) -> list[dict[str, Any]]:
    """Return adapter metadata; empty unless upstream_adapters_enabled."""
    _bootstrap_registry()
    settings = settings or load_settings()
    if not settings.upstream_adapters_enabled:
        return []
    out: list[dict[str, Any]] = []
    for adapter in _REGISTRY.values():
        out.append(
            {
                "protocol_id": adapter.protocol_id,
                "protocol_version": adapter.protocol_version,
                "upstream_pin": adapter.upstream_pin,
                "capabilities": {
                    "needs_logprobs": adapter.capabilities.needs_logprobs,
                    "needs_tools": adapter.capabilities.needs_tools,
                    "needs_sandbox": adapter.capabilities.needs_sandbox,
                    "needs_schema_enforcement": adapter.capabilities.needs_schema_enforcement,
                },
            }
        )
    return sorted(out, key=lambda row: row["protocol_id"])


_bootstrap_registry()