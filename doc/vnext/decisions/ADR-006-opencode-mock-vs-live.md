# ADR-006: Mock harness in CI; live OpenCode only after validated pin

**Status:** accepted  
**Date:** 2026-11-21  
**Work packages:** WP7, WP8

## Context

Spec mandates OpenCode as the sole creative harness but forbids claiming compaction/usage capture without validation. CI must not call production inference.

## Decision

- **`mock_harness.materialize_static_app`** is the only harness used in automated tests and default dev API (`POST /api/creative/attempts/mock`).
- **`opencode_driver.run_attempt`** raises `NotImplementedError` until a pinned version and owner-approved short test pass (document pin in worker compose when live).
- No Pi/OMP/ZooCode adapters in this release (spec §11.1).

## Consequences

- Gallery/preview UX can be built against mock attempts before OpenCode lands.
- Replacing mock with live driver is a bounded change at `opencode_driver` + worker image, not a UI rewrite.