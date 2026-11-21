# ADR-005: Creative Arena and coding execution disabled by default

**Status:** accepted  
**Date:** 2026-11-21  
**Work packages:** WP4, WP7, WP8

## Context

Spec §7.2 and §11.7: subprocess timeout is not sandboxing; generated code and agent tools are untrusted until an isolated worker passes security gates.

## Decision

- **`coding_execution_enabled`** (settings, default `false`): LiveCodeBench-style execution in [`coding.py`](../../../src/benchbase/runners/coding.py) returns `infrastructure` / `coding_execution_disabled` when off.
- **`creative_arena_enabled`** / **`BENCHBASE_CREATIVE_ARENA`**: Creative API returns 403 until enabled.
- **`agentic_omp_enabled`** (default `false`): legacy OMP agentic path stays archived; no new UI dependence on Bun/OMP mounts for vNext Creative Arena.

## Consequences

- Standard coding scores may show failures with infrastructure reason until owner enables execution **after** WP7 worker review—not by flipping the flag alone.
- Creative UI can ship behind env/settings without exposing attack surface.