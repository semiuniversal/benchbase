"""Isolated worker boundary — controller only; agent runs in separate process (WP7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkerLaunchSpec:
    attempt_uuid: str
    workspace: Path
    network_policy: str = "deny_by_default"
    memory_mb: int = 2048
    cpu_limit: float = 2.0


def validate_workspace_path(root: Path, rel: str) -> Path | None:
    try:
        resolved = (root / rel).resolve()
        if not str(resolved).startswith(str(root.resolve())):
            return None
        return resolved
    except (OSError, ValueError):
        return None