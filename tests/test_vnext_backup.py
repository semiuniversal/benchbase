"""WP0: backup round-trip preserves table row counts."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from benchbase.db.models import Base, Model, ModelStatus
from sqlalchemy import create_engine

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "vnext_backup.py"


def _seed_db(path: Path) -> dict[str, int]:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            Model.__table__.insert(),
            [
                {
                    "name": "demo",
                    "endpoint_url": "http://127.0.0.1",
                    "status": ModelStatus.ACTIVE.value,
                    "is_active": True,
                    "color": "blue",
                    "context_window_manual": False,
                    "supports_vision": False,
                }
            ],
        )
    raw = sqlite3.connect(path)
    try:
        tables = [
            r[0]
            for r in raw.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: raw.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0] for t in tables}
    finally:
        raw.close()


def test_sqlite_backup_roundtrip(tmp_path):
    src = tmp_path / "benchbase.db"
    before = _seed_db(src)
    dest = tmp_path / "backup.db"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--data-dir", str(tmp_path), "--out", str(dest)],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    )
    assert proc.returncode == 0
    after_conn = sqlite3.connect(dest)
    try:
        for table, n in before.items():
            got = after_conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            assert got == n, table
    finally:
        after_conn.close()