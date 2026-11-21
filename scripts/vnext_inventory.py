#!/usr/bin/env python3
"""Inventory schema counts and corpus MANIFEST hashes (WP0)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def corpus_manifests() -> list[dict]:
    out: list[dict] = []
    suites = REPO_ROOT / "corpus" / "suites"
    for path in sorted(suites.glob("**/MANIFEST.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        out.append({
            "path": str(path.relative_to(REPO_ROOT)),
            "axis": data.get("axis"),
            "suite_version": data.get("suite_version"),
            "content_hash": data.get("content_hash"),
            "item_count": data.get("item_count"),
        })
    return out


def db_inventory(db_path: Path) -> dict:
    if not db_path.exists():
        return {"error": f"missing {db_path}"}
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0] for t in sorted(tables)}
        return {"db_path": str(db_path), "table_counts": counts}
    finally:
        conn.close()


def main() -> int:
    import os

    data_dir = Path(os.environ.get("BENCHBASE_DATA_DIR", REPO_ROOT / "docker" / "data"))
    if not (data_dir / "benchbase.db").exists():
        data_dir = REPO_ROOT
    report = {
        "database": db_inventory(data_dir / "benchbase.db"),
        "corpus_manifests": corpus_manifests(),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())