"""WP6 adapter registry and feature flag."""

from benchbase.adapters.registry import adapter_descriptors, get_adapter
from benchbase.config import Settings


def test_adapters_hidden_when_flag_off():
    settings = Settings(upstream_adapters_enabled=False)
    assert adapter_descriptors(settings) == []


def test_adapters_listed_when_flag_on():
    settings = Settings(upstream_adapters_enabled=True)
    rows = adapter_descriptors(settings)
    assert any(r["protocol_id"] == "aiperf.headless.v0" for r in rows)
    stub = get_adapter("aiperf.headless.v0")
    assert stub is not None
    assert stub.upstream_pin == "TBD"