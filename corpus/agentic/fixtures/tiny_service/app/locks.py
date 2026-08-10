"""File lock helper used by failure-injection tasks."""
from __future__ import annotations
from pathlib import Path

def write_guarded(path: Path, content: str) -> None:
    """Write content; if .fail_once_lock exists, fail once then remove the flag."""
    flag = path.parent / ".fail_once_lock"
    if flag.exists():
        flag.unlink(missing_ok=True)
        raise OSError("resource temporarily locked")
    path.write_text(content, encoding="utf-8")
