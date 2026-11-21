# WP3 — Evidence and identity

**ADR:** [ADR-003](../decisions/ADR-003-evidence-sqlite-plus-artifacts.md), [ADR-004](../decisions/ADR-004-schema-init-db-then-alembic.md)

**Depends on:** WP0

## Touch list

- `src/benchbase/db/models.py` — DeploymentRevision, EvidenceObservation
- `src/benchbase/evidence/store.py`
- `src/benchbase/db/session.py` — table create
- `tests/test_vnext_evidence.py`