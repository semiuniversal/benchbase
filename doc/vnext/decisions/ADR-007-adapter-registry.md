# ADR-007: Upstream benchmarks via adapters registry

**Status:** accepted  
**Date:** 2026-11-21  
**Work packages:** WP6

## Context

Spec §6.3 requires native legacy profile frozen while canonical upstream pieces integrate behind explicit protocol IDs and pins.

## Decision

- Define [`BenchmarkAdapter`](../../../src/benchbase/adapters/base.py) with capabilities, `protocol_id`, `protocol_version`, optional `upstream_pin`.
- Register instances in [`adapters/registry.py`](../../../src/benchbase/adapters/registry.py).
- Gate registration behind **`upstream_adapters_enabled`** (settings, default `false`). Legacy runners in `runners/` remain default until an adapter is qualified per WP6 plan.

## Consequences

- No automatic install of LM Harness, BFCL upstream, AIPerf in base image.
- Each new adapter needs its own ADR entry or WP6 plan amendment for pin and deviation labels.