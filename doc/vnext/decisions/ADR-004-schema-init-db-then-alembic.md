# ADR-004: Keep init_db() for additive vNext tables; add Alembic before destructive migrations

**Status:** accepted  
**Date:** 2026-11-21  
**Work packages:** WP3

## Context

BenchBase today uses `Base.metadata.create_all()` plus hand-written `ALTER` in [`session.init_db`](../../../src/benchbase/db/session.py). Alembic is a dependency but unused. Spec requires non-destructive upgrades.

## Decision

- **vNext additive entities** (`DeploymentRevision`, `EvidenceObservation`, `ArenaSession`, `CreativeChallengeRevision`, `CreativeAttempt`) ship via `create_all` on existing deploy path.
- **Before** any column drop, table rewrite, or data backfill that cannot be done with `ALTER`, add Alembic revisions and a documented upgrade command (WP3 completion gate).
- Never tie ranking/score migration to a DB wipe; `init_db` must not wipe production runs for vNext features.

## Consequences

- Two migration paths briefly coexist; ADR supersedes only when Alembic owns a given change.
- Agents must read this ADR before adding non-additive schema.