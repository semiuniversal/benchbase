"""Single-instance BenchBase server lifecycle (dev CLI)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from benchbase.config import DATA_DIR

DEFAULT_PORT = 8000
STATE_PATH = DATA_DIR / ".benchbase-server.json"


def read_state() -> dict[str, Any] | None:
    if not STATE_PATH.is_file():
        return None
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_state(port: int, pid: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"pid": pid, "port": port, "ppid": os.getppid()}),
    )


def clear_state() -> None:
    try:
        STATE_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_pid(pid: int) -> bool:
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False


def _pids_on_port(port: int) -> list[int]:
    try:
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return [int(p) for p in out.stdout.strip().split() if p.isdigit()]
    except FileNotFoundError:
        pass

    try:
        out = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
            check=False,
        )
        pids: list[int] = []
        for line in out.stdout.splitlines():
            if f":{port}" in line and "pid=" in line:
                for segment in line.split(","):
                    if segment.startswith("pid="):
                        pids.append(int(segment.split("=")[1].split(",")[0]))
        return pids
    except FileNotFoundError:
        return []


def kill_port_listeners(port: int, own_pid: int | None = None) -> list[int]:
    """SIGTERM processes listening on port; return PIDs killed."""
    own = own_pid if own_pid is not None else os.getpid()
    killed: list[int] = []
    for pid in set(_pids_on_port(port)):
        if pid == own:
            continue
        if _kill_pid(pid):
            killed.append(pid)
    if killed:
        time.sleep(0.25)
    return killed


def stop_registered_server() -> tuple[int | None, int | None, list[int]]:
    """Stop server recorded in the pid file. Returns (old_pid, old_port, ports_killed)."""
    state = read_state()
    if not state:
        return None, None, []

    old_pid = int(state.get("pid", 0))
    old_port = int(state.get("port", 0))
    ports_killed: list[int] = []

    if pid_alive(old_pid):
        _kill_pid(old_pid)
        time.sleep(0.25)
        if pid_alive(old_pid):
            try:
                os.kill(old_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    if old_port:
        ports_killed = kill_port_listeners(old_port)

    clear_state()
    return old_pid, old_port, ports_killed


def ensure_single_server(port: int) -> list[str]:
    """
    Stop any previous BenchBase server (pid file + port listeners).
    Returns human-readable log lines for the CLI.
    """
    lines: list[str] = []
    old_pid, old_port, killed_on_old = stop_registered_server()

    if old_pid and pid_alive(old_pid):
        lines.append(f"Stopped previous BenchBase (pid {old_pid}, port {old_port})")
    elif old_pid:
        lines.append(f"Removed stale server record (pid {old_pid} was not running)")

    killed_on_target = kill_port_listeners(port)
    for pid in sorted(set(killed_on_target) - {old_pid or 0}):
        lines.append(f"Stopped process {pid} on port {port}")

    return lines


def status_message() -> str:
    state = read_state()
    if not state:
        return "BenchBase is not running (no server record)."

    pid = int(state.get("pid", 0))
    port = int(state.get("port", DEFAULT_PORT))
    if pid_alive(pid):
        return f"BenchBase is running — pid {pid}, http://127.0.0.1:{port}"
    return (
        f"BenchBase is not running (stale record: pid {pid}, port {port}). "
        f"Run `uv run benchbase serve` to start fresh."
    )
