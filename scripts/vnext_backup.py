#!/usr/bin/env python3
"""Consistent SQLite backup for BenchBase (WP0).

Uses sqlite3.Connection.backup() so WAL mode is captured safely without
stopping the server when the source connection can obtain a shared lock.
For production Docker deploys, prefer stopping the container first (see doc/vnext).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def default_data_dir() -> Path:
    import os

    env = os.environ.get("BENCHBASE_DATA_DIR")
    if env:
        return Path(env)
    docker = REPO_ROOT / "docker" / "data"
    if docker.is_dir() and (docker / "benchbase.db").exists():
        return docker
    return REPO_ROOT


def sqlite_backup(src: Path, dest: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Database not found: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30.0)
    dest_conn = sqlite3.connect(dest)
    try:
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()


def table_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0] for t in sorted(tables)}
    finally:
        conn.close()


def write_manifest(out_dir: Path, counts: dict[str, int], src: Path) -> Path:
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(src),
        "table_counts": counts,
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="BenchBase SQLite backup (vNext WP0)")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Data directory containing benchbase.db",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output .db file or .tar.gz archive",
    )
    parser.add_argument(
        "--tar",
        action="store_true",
        help="Bundle data dir into tar.gz (excludes live WAL; uses backup copy)",
    )
    args = parser.parse_args()

    data_dir = args.data_dir or default_data_dir()
    db_src = data_dir / "benchbase.db"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_root = REPO_ROOT / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)

    if args.tar:
        out = args.out or (backup_root / f"benchbase-data-{stamp}.tar.gz")
        tmp_db = backup_root / f"benchbase.db.{stamp}"
        sqlite_backup(db_src, tmp_db)
        counts = table_counts(tmp_db)
        manifest = write_manifest(backup_root, counts, db_src)
        with tarfile.open(out, "w:gz") as tar:
            tar.add(tmp_db, arcname="benchbase.db")
            tar.add(manifest, arcname="manifest.json")
            run_logs = data_dir / "run_logs"
            if run_logs.is_dir():
                tar.add(run_logs, arcname="run_logs")
        tmp_db.unlink(missing_ok=True)
        print(json.dumps({"archive": str(out), "table_counts": counts}, indent=2))
        return 0

    out = args.out or (backup_root / f"benchbase.db.{stamp}")
    sqlite_backup(db_src, out)
    counts = table_counts(out)
    write_manifest(out.parent, counts, db_src)
    print(json.dumps({"backup_db": str(out), "table_counts": counts}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)