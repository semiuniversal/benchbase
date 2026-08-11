"""Durable agentic attempt transcripts + live event bus for Inspect Session."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from benchbase.config import DATA_DIR

AGENTIC_DIR = DATA_DIR / "agentic"


def run_dir(run_id: int) -> Path:
    path = AGENTIC_DIR / str(run_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def item_id(task_id: str, seed: int) -> str:
    return f"{task_id}:seed{seed}"


def transcript_filename(task_id: str, seed: int) -> str:
    safe = task_id.replace("/", "_")
    return f"{safe}-seed{seed}.jsonl"


def transcript_relpath(run_id: int, task_id: str, seed: int) -> str:
    return f"agentic/{run_id}/{transcript_filename(task_id, seed)}"


def transcript_abspath(run_id: int, task_id: str, seed: int) -> Path:
    return run_dir(run_id) / transcript_filename(task_id, seed)


def current_path(run_id: int) -> Path:
    return run_dir(run_id) / "current.json"


def write_current(
    run_id: int,
    *,
    item_id_value: str,
    task_id: str,
    seed: int,
    fixture: str,
    instruction: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "item_id": item_id_value,
        "task_id": task_id,
        "seed": seed,
        "fixture": fixture,
        "started_at": time.time(),
    }
    if instruction is not None:
        payload["instruction"] = instruction
    current_path(run_id).write_text(json.dumps(payload) + "\n", encoding="utf-8")


def clear_current(run_id: int) -> None:
    path = current_path(run_id)
    if path.is_file():
        path.unlink(missing_ok=True)


def read_current(run_id: int) -> dict[str, Any] | None:
    path = current_path(run_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def list_transcript_files(run_id: int) -> list[Path]:
    d = AGENTIC_DIR / str(run_id)
    if not d.is_dir():
        return []
    return sorted(d.glob("*-seed*.jsonl"))


def parse_item_id_from_filename(name: str) -> tuple[str, int] | None:
    # greet-welcome-seed0.jsonl
    if not name.endswith(".jsonl"):
        return None
    stem = name[: -len(".jsonl")]
    if "-seed" not in stem:
        return None
    task_part, _, seed_s = stem.rpartition("-seed")
    try:
        return task_part, int(seed_s)
    except ValueError:
        return None


@dataclass
class AttemptEvent:
    raw: dict[str, Any]
    ts: float = field(default_factory=time.time)


class AttemptBuffer:
    """Per-attempt fan-out for live SSE subscribers."""

    def __init__(self, run_id: int, item: str) -> None:
        self.run_id = run_id
        self.item = item
        self._queues: list[asyncio.Queue[AttemptEvent | None]] = []
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        try:
            self._loop = loop or asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def publish(self, event: AttemptEvent) -> None:
        if self._closed:
            return
        for queue in list(self._queues):
            try:
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(queue.put_nowait, event)
                else:
                    queue.put_nowait(event)
            except Exception:
                pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for queue in list(self._queues):
            try:
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(queue.put_nowait, None)
                else:
                    queue.put_nowait(None)
            except Exception:
                pass

    async def subscribe(self) -> AsyncIterator[AttemptEvent]:
        queue: asyncio.Queue[AttemptEvent | None] = asyncio.Queue()
        self._queues.append(queue)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if queue in self._queues:
                self._queues.remove(queue)


class AttemptEventBus:
    _buffers: dict[tuple[int, str], AttemptBuffer] = {}

    @classmethod
    def open(cls, run_id: int, item: str) -> AttemptBuffer:
        key = (run_id, item)
        buf = AttemptBuffer(run_id, item)
        try:
            buf.bind_loop()
        except Exception:
            pass
        cls._buffers[key] = buf
        return buf

    @classmethod
    def get(cls, run_id: int, item: str) -> AttemptBuffer | None:
        return cls._buffers.get((run_id, item))

    @classmethod
    def close(cls, run_id: int, item: str) -> None:
        key = (run_id, item)
        buf = cls._buffers.pop(key, None)
        if buf is not None:
            buf.close()


class TranscriptWriter:
    """Append-only JSONL writer + optional live bus publish (thread-safe)."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: int | None = None,
        item: str | None = None,
        bus: AttemptBuffer | None = None,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self.run_id = run_id
        self.item = item
        self.bus = bus
        self._fh = self.path.open("a", encoding="utf-8")

    def write_event(self, ev: dict[str, Any]) -> None:
        line = json.dumps(ev, default=str)
        self._fh.write(line + "\n")
        self._fh.flush()
        if self.bus is not None:
            self.bus.publish(AttemptEvent(raw=ev))

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass
        if self.bus is not None:
            self.bus.close()

    def __enter__(self) -> TranscriptWriter:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def read_raw_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def normalize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce OMP RPC noise to UI turns: instruction, assistant text, tools."""
    turns: list[dict[str, Any]] = []
    for ev in events:
        etype = str(ev.get("type") or "")
        ts = ev.get("timestamp") or ev.get("ts")
        if etype == "response" and ev.get("command") == "prompt":
            # prompt ack — instruction already known to UI; skip unless message present
            continue
        if etype == "message_end":
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else None
            if not msg:
                continue
            role = str(msg.get("role") or "")
            content = msg.get("content")
            text = _content_to_text(content)
            if role == "user":
                if turns and turns[-1].get("kind") == "user" and turns[-1].get("text") == text:
                    continue
                turns.append({"kind": "user", "role": "user", "text": text, "ts": ts})
            elif role == "assistant" and text.strip():
                turns.append({"kind": "assistant", "role": "assistant", "text": text, "ts": ts})
            continue
        # Fixture / print-mode shapes
        if etype in {"assistant", "message"} or str(ev.get("role") or "") == "assistant":
            text = _content_to_text(ev.get("content") or ev.get("text") or "")
            if text.strip():
                turns.append({"kind": "assistant", "role": "assistant", "text": text, "ts": ts})
            continue
        if etype in {"user", "human"} or str(ev.get("role") or "") == "user":
            text = _content_to_text(ev.get("content") or ev.get("text") or "")
            if turns and turns[-1].get("kind") == "user" and turns[-1].get("text") == text:
                continue
            if text.strip():
                turns.append({"kind": "user", "role": "user", "text": text, "ts": ts})
            continue
        if etype in {"tool_execution_start", "tool_call", "toolUse", "tool_use"}:
            turns.append(
                {
                    "kind": "tool_call",
                    "tool": str(ev.get("toolName") or ev.get("name") or "unknown"),
                    "args": ev.get("args") or ev.get("arguments") or {},
                    "toolCallId": ev.get("toolCallId"),
                    "ts": ts,
                }
            )
            continue
        if etype in {"tool_execution_end", "tool_result"}:
            result = ev.get("result") if "result" in ev else ev.get("content")
            result_text = result if isinstance(result, str) else json.dumps(result, default=str)[:4000]
            turns.append(
                {
                    "kind": "tool_result",
                    "tool": str(ev.get("toolName") or ev.get("name") or "unknown"),
                    "result": result_text,
                    "isError": bool(ev.get("isError")),
                    "toolCallId": ev.get("toolCallId"),
                    "ts": ts,
                }
            )
            continue
        if etype in {"agent_end", "idle", "done"}:
            turns.append({"kind": "end", "type": etype, "ts": ts})
    return turns


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block.get("text"), str):
                    parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""
