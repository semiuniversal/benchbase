"""Filesystem evidence store with content-addressed paths."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from benchbase.config import DATA_DIR


def artifact_root() -> Path:
    root = DATA_DIR / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def observation_dir(run_id: int, item_id: str) -> Path:
    safe_item = item_id.replace("/", "_")[:128]
    path = artifact_root() / "observations" / str(run_id) / safe_item
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_observation_manifest(
    run_id: int,
    item_id: str,
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Write manifest; return (relative_path, sha256)."""
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    d = observation_dir(run_id, item_id)
    manifest = d / "manifest.json"
    manifest.write_bytes(body)
    rel = manifest.relative_to(artifact_root()).as_posix()
    return rel, digest