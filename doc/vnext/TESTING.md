# vNext phase delivery — testing protocol

Before marking a work package **delivered** on [CHECKLIST.md](CHECKLIST.md):

1. **Unit/integration:** `uv sync --group dev && uv run pytest` (all tests under `tests/`; corpus fixtures excluded via `pyproject.toml`).
2. **WP-specific:** run files matching `tests/test_vnext_wp*py` and `tests/test_vnext_*.py` for the phase.
3. **Frontend (UI phases):** `cd frontend && npm run build`.
4. **Manual sanity (owner when possible):** Compare cohort badge, Arena tok/s vs chunk/s, CSV export columns.

## WP0

- `tests/test_vnext_backup.py`, `tests/test_vnext_wp0_restore.py`
- Optional host: `uv run python scripts/vnext_inventory.py` against production data dir (owner).

## WP1

- `tests/test_vnext_cohorts.py`, `tests/test_vnext_wp1_*.py`, `tests/test_gate_axes.py`

## WP2

- `tests/test_arena_metrics.py`, `tests/test_vnext_wp2_coding_gate.py`

No production inference endpoints in CI.