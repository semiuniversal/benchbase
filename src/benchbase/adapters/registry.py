from __future__ import annotations

from benchbase.adapters.base import BenchmarkAdapter

_REGISTRY: dict[str, BenchmarkAdapter] = {}


def register_adapter(adapter: BenchmarkAdapter) -> None:
    _REGISTRY[adapter.protocol_id] = adapter


def get_adapter(protocol_id: str) -> BenchmarkAdapter | None:
    return _REGISTRY.get(protocol_id)