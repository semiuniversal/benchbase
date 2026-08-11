"""Helpers for Inspect Session workspace tree (fixture-rooted, path-safe)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benchbase.agentic.workspace import FIXTURES_ROOT, fixture_src


_SKIP_NAMES = {".git", "FIXTURE.json", "state.hash", "__pycache__"}


def list_fixture_tree(fixture: str) -> list[dict[str, Any]]:
    root = fixture_src(fixture)
    if not root.is_dir():
        raise FileNotFoundError(f"Fixture not found: {fixture}")
    entries: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        parts = rel.split("/")
        if any(part in _SKIP_NAMES or part.endswith(".pyc") for part in parts):
            continue
        if p.is_dir():
            entries.append({"path": rel, "type": "dir"})
        elif p.is_file():
            entries.append({"path": rel, "type": "file", "size": p.stat().st_size})
    return entries


def read_fixture_file(fixture: str, rel_path: str) -> str:
    root = fixture_src(fixture).resolve()
    # Normalize and prevent traversal
    candidate = (root / rel_path).resolve()
    if not str(candidate).startswith(str(root) + "/") and candidate != root:
        raise PermissionError("Path escapes fixture root")
    if not candidate.is_file():
        raise FileNotFoundError(rel_path)
    # Cap large files
    data = candidate.read_bytes()
    if len(data) > 512_000:
        return data[:512_000].decode("utf-8", errors="replace") + "\n… [truncated]"
    return data.decode("utf-8", errors="replace")


def resolve_fixture_for_item(task_id: str, suite_hint: str | None = None) -> str | None:
    """Look up fixture name from task.yaml under mvp/headline."""
    from benchbase.agentic.tasks import TASKS_ROOT
    import yaml

    suites = [suite_hint] if suite_hint else ["mvp", "headline"]
    for suite in suites:
        if not suite:
            continue
        root = TASKS_ROOT / suite
        if not root.is_dir():
            continue
        for d in root.iterdir():
            yaml_path = d / "task.yaml"
            if not yaml_path.is_file():
                continue
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if str(data.get("id")) == task_id:
                return str(data.get("fixture") or "")
    return None
