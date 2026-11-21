"""Creative workspace provisioning."""

import json
from pathlib import Path

from benchbase.creative.workspace import attempt_root, provision_attempt_workspace


def test_provision_layout(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BENCHBASE_DATA_DIR", str(tmp_path))
    from benchbase import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    root = provision_attempt_workspace("abc-123", model_name="test-seat", harness="mock")
    assert root == attempt_root("abc-123")
    assert (root / "project").is_dir()
    assert (root / "logs" / "events.jsonl").is_file()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_name"] == "test-seat"
    assert (root / "opencode.jsonc").is_file()
    assert (root / ".opencode" / "skills" / "volcano-build" / "SKILL.md").is_file()
    assert (root / "project" / "BRIEF.md").is_file()