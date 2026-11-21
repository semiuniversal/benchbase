#!/usr/bin/env python3
"""Read-only diagnostics snapshot (WP4). No inference calls."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def locate_db() -> Path:
    import os

    for candidate in [
        Path(os.environ.get("BENCHBASE_DATA_DIR", "")) / "benchbase.db",
        REPO / "docker" / "data" / "benchbase.db",
        REPO / "benchbase.db",
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("benchbase.db not found")


def main() -> int:
    db_path = locate_db()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tool_items = conn.execute(
            """
            SELECT m.name AS model, ri.passed, ri.item_id
            FROM result_items ri
            JOIN results r ON r.id = ri.result_id
            JOIN runs ru ON ru.id = r.run_id
            JOIN models m ON m.id = ru.model_id
            JOIN benchmark_suites s ON s.id = ru.suite_id
            WHERE s.axis = 'tool_calling'
            """
        ).fetchall()
        tool_matrix = defaultdict(lambda: {"pass": 0, "fail": 0})
        for row in tool_items:
            key = row["model"]
            if row["passed"]:
                tool_matrix[key]["pass"] += 1
            else:
                tool_matrix[key]["fail"] += 1

        coding_zero = conn.execute(
            """
            SELECT m.name, r.score, ru.tier
            FROM results r
            JOIN runs ru ON ru.id = r.run_id
            JOIN models m ON m.id = ru.model_id
            JOIN benchmark_suites s ON s.id = ru.suite_id
            WHERE s.axis = 'coding' AND (r.score IS NULL OR r.score = 0)
            """
        ).fetchall()

        missing_tps = conn.execute(
            """
            SELECT m.name, r.metrics_json
            FROM results r
            JOIN runs ru ON ru.id = r.run_id
            JOIN models m ON m.id = ru.model_id
            JOIN benchmark_suites s ON s.id = ru.suite_id
            WHERE s.axis = 'speed' AND r.metrics_json IS NOT NULL
            """
        ).fetchall()
        no_output_tps = []
        for row in missing_tps:
            try:
                metrics = json.loads(row["metrics_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if metrics.get("output_tps") is None:
                no_output_tps.append(row["name"])

        unscored = conn.execute(
            """
            SELECT m.name, m.status
            FROM models m
            LEFT JOIN runs ru ON ru.model_id = m.id AND ru.status = 'completed'
            WHERE ru.id IS NULL AND m.status != 'archived'
            """
        ).fetchall()

        report = {
            "db_path": str(db_path),
            "bfcl_tool_calling_by_model": dict(tool_matrix),
            "coding_zero_or_null": [dict(r) for r in coding_zero],
            "speed_missing_output_tps_models": sorted(set(no_output_tps)),
            "models_without_completed_runs": [dict(r) for r in unscored],
        }
        out_dir = REPO / "doc" / "vnext" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "diagnostics-latest.json"
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"written": str(out_file), "summary": {
            "tool_models": len(tool_matrix),
            "coding_zeros": len(report["coding_zero_or_null"]),
            "missing_tps": len(report["speed_missing_output_tps_models"]),
        }}, indent=2))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)