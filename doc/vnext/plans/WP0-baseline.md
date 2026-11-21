# WP0 — Baseline

**Branch:** `feat/vnext/wp0-baseline`  
**Depends on:** —

## Scope

- Doc hub (`doc/vnext/*`)
- `scripts/vnext_backup.py` — SQLite `backup()` API + optional tar of `data/`
- `scripts/vnext_inventory.py` — row counts, suite hashes
- `tests/test_vnext_backup.py` — round-trip on temp DB

## Out of scope

- Schema changes, scoring changes

## Acceptance (spec §14)

- [ ] Restore tested on disposable copy
- [ ] Pre-upgrade counts verifiable via inventory script
- [ ] No production data modified by tests

## Rollback

Remove scripts; docs only.