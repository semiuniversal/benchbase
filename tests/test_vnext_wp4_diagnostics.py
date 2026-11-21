"""WP4: diagnostics script is read-only and writes report."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from benchbase.db.models import Base, BenchmarkAxis, BenchmarkSuite, Model, ModelStatus, Run, RunStatus
from sqlalchemy import create_engine

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "vnext_diagnostics.py"


def test_diagnostics_emits_report(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    db = data / "benchbase.db"
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            Model.__table__.insert(),
            {
                "name": "orphan",
                "endpoint_url": "http://127.0.0.1",
                "status": ModelStatus.ACTIVE.value,
                "is_active": True,
                "color": "blue",
                "context_window_manual": False,
                "supports_vision": False,
            },
        )
        # use ORM tables via raw insert for suite
        conn.execute(
            BenchmarkSuite.__table__.insert(),
            {
                "name": "Tools",
                "axis": BenchmarkAxis.TOOL_CALLING.value,
                "category": BenchmarkAxis.TOOL_CALLING.value,
                "runner_class": "tool_calling",
                "suite_version": "v2",
            },
        )
        suite_id = conn.execute(
            __import__("sqlalchemy").text("SELECT id FROM benchmark_suites LIMIT 1")
        ).scalar()
        model_id = conn.execute(
            __import__("sqlalchemy").text("SELECT id FROM models LIMIT 1")
        ).scalar()
        conn.execute(
            Run.__table__.insert(),
            {
                "model_id": model_id,
                "suite_id": suite_id,
                "status": RunStatus.COMPLETED.value,
                "tier": "standard",
            },
        )

    monkeypatch.setenv("BENCHBASE_DATA_DIR", str(data))
    out = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
    )
    payload = json.loads(out.stdout)
    assert "written" in payload
    report_path = Path(payload["written"])
    assert report_path.is_file()
    report = json.loads(report_path.read_text())
    assert "models_without_completed_runs" in report