"""Creative attempt event log (JSONL + in-process subscribers)."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}


@dataclass
class CreativeEvent:
    kind: str
    message: str = ""
    tool: str | None = None
    path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ts": time.time(),
            "kind": self.kind,
            "message": self.message,
        }
        if self.tool:
            out["tool"] = self.tool
        if self.path:
            out["path"] = self.path
        if self.extra:
            out.update(self.extra)
        return out


def _log_path(workspace_root: Path) -> Path:
    return workspace_root / "logs" / "events.jsonl"


async def emit(workspace_root: Path, attempt_uuid: str, event: CreativeEvent) -> None:
    payload = event.to_payload()
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    log_path = _log_path(workspace_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)
    for q in _subscribers.get(attempt_uuid, []):
        await q.put(payload)


def subscribe(attempt_uuid: str) -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _subscribers.setdefault(attempt_uuid, []).append(q)
    return q


def unsubscribe(attempt_uuid: str, q: asyncio.Queue[dict[str, Any]]) -> None:
    subs = _subscribers.get(attempt_uuid, [])
    if q in subs:
        subs.remove(q)


def replay(workspace_root: Path) -> list[dict[str, Any]]:
    path = _log_path(workspace_root)
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


async def stream_events(
    attempt_uuid: str,
    workspace_root: Path,
    *,
    terminal_status: asyncio.Event | None = None,
) -> AsyncIterator[dict[str, Any]]:
    for row in replay(workspace_root):
        yield row
    q = subscribe(attempt_uuid)
    try:
        while True:
            if terminal_status and terminal_status.is_set() and q.empty():
                break
            try:
                item = await asyncio.wait_for(q.get(), timeout=1.0)
                yield item
                if item.get("kind") in ("complete", "error", "cancelled"):
                    break
            except asyncio.TimeoutError:
                if terminal_status and terminal_status.is_set():
                    break
                continue
    finally:
        unsubscribe(attempt_uuid, q)