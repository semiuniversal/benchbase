"""Fixture instantiate/destroy with state-hash verification."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

AGENTIC_ROOT = Path(__file__).resolve().parents[3] / "corpus" / "agentic"
FIXTURES_ROOT = AGENTIC_ROOT / "fixtures"


def compute_state_hash(root: Path) -> str:
    """SHA-256 over sorted relative paths + file contents (excludes .git)."""
    h = hashlib.sha256()
    root = root.resolve()
    paths: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/") or rel == ".git":
            continue
        if rel in {"FIXTURE.json", "state.hash"}:
            continue
        paths.append(p)
    for p in sorted(paths, key=lambda x: x.relative_to(root).as_posix()):
        rel = p.relative_to(root).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def load_fixture_meta(name: str) -> dict[str, Any]:
    meta_path = FIXTURES_ROOT / name / "FIXTURE.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"Missing fixture metadata: {meta_path}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def fixture_src(name: str) -> Path:
    return FIXTURES_ROOT / name


def instantiate_fixture(
    name: str,
    *,
    dest_parent: Path | None = None,
    verify_hash: bool = True,
) -> Path:
    """Copy fixture tree into a disposable workspace; verify initial state-hash."""
    src = fixture_src(name)
    if not src.is_dir():
        raise FileNotFoundError(f"Fixture not found: {src}")
    meta = load_fixture_meta(name)
    parent = Path(dest_parent) if dest_parent else Path(tempfile.mkdtemp(prefix="bb-agentic-"))
    parent.mkdir(parents=True, exist_ok=True)
    dest = parent / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns(".git", "FIXTURE.json", "state.hash", "__pycache__", "*.pyc"),
    )
    if verify_hash:
        expected = meta.get("state_hash") or ""
        actual = compute_state_hash(dest)
        if expected and actual != expected:
            destroy_workspace(dest)
            raise RuntimeError(
                f"Fixture {name} state-hash mismatch: expected {expected}, got {actual} "
                "(fixture drift — re-record state.hash)"
            )
    return dest


def destroy_workspace(path: Path | str) -> None:
    p = Path(path)
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
    parent = p.parent
    # Remove empty temp parent created by instantiate_fixture when we own it.
    if parent.exists() and parent.name.startswith("bb-agentic-"):
        try:
            parent.rmdir()
        except OSError:
            pass


def record_state_hash(name: str) -> str:
    """Compute and write state.hash + update FIXTURE.json for a fixture source tree."""
    src = fixture_src(name)
    # Hash the tree as it will be instantiated (without meta files).
    tmp = Path(tempfile.mkdtemp(prefix="bb-hash-"))
    try:
        dest = tmp / name
        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns(".git", "FIXTURE.json", "state.hash", "__pycache__", "*.pyc"),
        )
        digest = compute_state_hash(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    (src / "state.hash").write_text(digest + "\n", encoding="utf-8")
    meta_path = src / "FIXTURE.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    meta["name"] = name
    meta["state_hash"] = digest
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return digest
