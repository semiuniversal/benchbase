# Repository reconciliation (vNext WP0)

**Commit at reconciliation:** `a1532f2` (audit docs) + vNext implementation branch  
**Spec:** v1.2 (2026-11-21)

## Deployment

| Item | Verified |
|------|----------|
| Docker compose | Single `benchbase` service; data at `BENCHBASE_DATA_DIR` / `docker/data` |
| SQLite WAL | Used; backups must use SQLite backup API or stopped container |
| OMP/Bun mounts | Legacy agentic; retired in WP7 behind `agentic_omp_enabled` |

## Persistence

| Item | Verified |
|------|----------|
| ORM | `Model`, `Run`, `Result`, `ResultItem`, `BenchmarkSuite`, `SettingEntry` |
| Migrations | `init_db()` + additive `ALTER`; Alembic stamp `20261123_0001` (no-op baseline) |
| Corpus | Frozen `corpus/suites/*/v2` (long_context v3); `content_hash` on suites |

## Known gaps (pre-vNext)

| Finding | WP |
|---------|-----|
| Global Borda includes smoke-only deployments | WP1 |
| Arena TPS = chunks/sec | WP2 |
| `raw_answer` often truncated | WP3 evidence |
| `litellm_*` setting names | WP9 |
| Coding subprocess on host, not sandboxed | WP4 + WP7 |

## Test baseline

```bash
uv run pytest
```

No production DB opened during automated tests; use temp SQLite.

## Changes since audited commit `8543f6f`

- Methodology audit + response documents added (`a1532f2`).
- vNext spec `doc/BenchBase_vNext_Specification_v1.2.md` (untracked until WP0 commit).

## 2026-11-23

- Speed suite config: dual prefill `pp` 4096 + 32768 for decode-32k profile sibling.
- Evidence checkpoints attach `llm_evidence` + append-only `evaluator_results`.
- Export/import packages and capabilities API v2 shipped.

_Update this file only for material baseline deltas after WP0._