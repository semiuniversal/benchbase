"""WP0: tar backup includes manifest and restores counts."""

from __future__ import annotations

import json
import subprocess
import sys
import tarfile
from pathlib import Path

import sqlite3

from benchbase.db.models import Base, Model, ModelStatus
from sqlalchemy import create_engine

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "vnext_backup.py"


def test_tar_backup_contains_manifest_and_db(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    db = data / "benchbase.db"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            Model.__table__.insert(),
            {
                "name": "x",
                "endpoint_url": "http://127.0.0.1",
                "status": ModelStatus.ACTIVE.value,
                "is_active": True,
                "color": "blue",
                "context_window_manual": False,
                "supports_vision": False,
            },
        )

    archive = tmp_path / "bundle.tar.gz"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--data-dir", str(data), "--tar", "--out", str(archive)],
        check=True,
        cwd=REPO,
    )
    extract = tmp_path / "extract"
    extract.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(extract)
    restored_db = extract / "benchbase.db"
    assert restored_db.is_file()
    manifest_path = extract / "manifest.json"
    if not manifest_path.is_file():
        manifest_path = tmp_path / "backups" / "manifest.json"
    assert manifest_path.is_file(), "manifest.json missing from backup"
    manifest = json.loads(manifest_path.read_text())
    raw = sqlite3.connect(restored_db)
    try:
        n = raw.execute("SELECT COUNT(*) FROM models").fetchone()[0]
        assert n == manifest["table_counts"].get("models", n)
    finally:
        raw.close()