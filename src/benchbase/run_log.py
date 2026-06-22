"""Benchmark run log buffers with disk persistence for replay after restart."""

from __future__ import annotations

import asyncio
import contextvars
import json
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from benchbase.config import DATA_DIR

run_log_context: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "run_log_context", default=None
)

LOG_DIR = DATA_DIR / "run_logs"


@dataclass
class _LogLine:
    stream: str
    text: str


class RunLogBuffer:
    """Per-run log buffer with replay + live subscriber fan-out."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        self._lines: list[_LogLine] = []
        self._queues: list[asyncio.Queue[_LogLine | None]] = []
        self._closed = False

    def append(self, text: str, stream: str = "stdout") -> None:
        if not text:
            return
        entry = _LogLine(stream=stream, text=text)
        self._lines.append(entry)
        RunLogManager._write_disk_line(self.run_id, entry)
        for queue in self._queues:
            queue.put_nowait(entry)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for queue in self._queues:
            queue.put_nowait(None)

    async def subscribe(self) -> AsyncIterator[_LogLine]:
        queue: asyncio.Queue[_LogLine | None] = asyncio.Queue()
        self._queues.append(queue)
        try:
            for entry in self._lines:
                yield entry
            while not self._closed:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if queue in self._queues:
                self._queues.remove(queue)


class RunLogManager:
    _buffers: dict[int, RunLogBuffer] = {}

    @classmethod
    def _log_path(cls, run_id: int) -> Path:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        return LOG_DIR / f"{run_id}.jsonl"

    @classmethod
    def _write_disk_line(cls, run_id: int, entry: _LogLine) -> None:
        path = cls._log_path(run_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"stream": entry.stream, "text": entry.text}) + "\n")

    @classmethod
    def read_disk_log(cls, run_id: int) -> list[_LogLine]:
        path = cls._log_path(run_id)
        if not path.is_file():
            return []
        lines: list[_LogLine] = []
        with path.open(encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    lines.append(_LogLine(stream=data.get("stream", "stdout"), text=data["text"]))
                except (json.JSONDecodeError, KeyError):
                    lines.append(_LogLine(stream="stdout", text=raw + "\n"))
        return lines

    @classmethod
    def has_disk_log(cls, run_id: int) -> bool:
        return cls._log_path(run_id).is_file()

    @classmethod
    async def replay_disk(cls, run_id: int) -> AsyncIterator[_LogLine]:
        for entry in cls.read_disk_log(run_id):
            yield entry

    @classmethod
    def open(cls, run_id: int) -> RunLogBuffer:
        path = cls._log_path(run_id)
        if path.exists():
            path.unlink()
        buffer = RunLogBuffer(run_id)
        cls._buffers[run_id] = buffer
        return buffer

    @classmethod
    def get(cls, run_id: int) -> RunLogBuffer | None:
        return cls._buffers.get(run_id)

    @classmethod
    def append(cls, run_id: int, text: str, stream: str = "stdout") -> None:
        from benchbase.run_timing import RunTimingTracker

        RunTimingTracker.on_log_line(run_id, text)
        buffer = cls._buffers.get(run_id)
        if buffer:
            buffer.append(text, stream=stream)
        else:
            cls._write_disk_line(run_id, _LogLine(stream=stream, text=text))

    @classmethod
    def log(cls, run_id: int, message: str) -> None:
        cls.append(run_id, message + "\n", stream="system")

    @classmethod
    def close(cls, run_id: int) -> None:
        from benchbase.run_timing import RunTimingTracker

        RunTimingTracker.clear(run_id)
        buffer = cls._buffers.get(run_id)
        if buffer:
            buffer.close()

    @classmethod
    def remove(cls, run_id: int) -> None:
        cls._buffers.pop(run_id, None)
        path = cls._log_path(run_id)
        if path.exists():
            path.unlink()
