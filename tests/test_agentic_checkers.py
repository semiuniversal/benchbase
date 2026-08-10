"""Checker-tested: fail on pristine fixture, pass on golden patches."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from benchbase.agentic.tasks import load_tasks
from benchbase.agentic.workspace import destroy_workspace, instantiate_fixture

_GOLDEN = {
    "greet-welcome": {
        "src/greet.py": textwrap.dedent(
            '''\
            """Greeting helper for the tiny CLI fixture."""

            def greet(name: str) -> str:
                return f"Welcome, {name}!"


            def shout(name: str) -> str:
                return greet(name).upper()
            '''
        ),
    },
    "cli-verbose": {
        "src/cli.py": textwrap.dedent(
            '''\
            """Tiny CLI entrypoint."""
            from __future__ import annotations
            import argparse
            import sys
            from .greet import greet
            from .mathutil import add

            def main(argv: list[str] | None = None) -> int:
                p = argparse.ArgumentParser(prog="tiny-cli")
                p.add_argument("name", nargs="?", default="world")
                p.add_argument("--add", nargs=2, type=int, metavar=("A", "B"))
                p.add_argument("--verbose", action="store_true")
                args = p.parse_args(argv)
                if args.verbose:
                    print("verbose: on", file=sys.stderr)
                if args.add:
                    print(add(args.add[0], args.add[1]))
                    return 0
                print(greet(args.name))
                return 0

            if __name__ == "__main__":
                raise SystemExit(main())
            '''
        ),
    },
    "clamp-fix": {
        "src/mathutil.py": textwrap.dedent(
            '''\
            """Small math helpers."""

            def clamp_index(i: int, length: int) -> int:
                if length <= 0:
                    return 0
                if i < 0:
                    return 0
                if i > length - 1:
                    return length - 1
                return i


            def add(a: int, b: int) -> int:
                return a + b
            '''
        ),
    },
    "config-default-name": {
        "config.toml": textwrap.dedent(
            '''\
            [app]
            name = "tiny-cli"
            default_name = "friend"
            log_level = "info"
            '''
        ),
    },
    "cors-star": {
        "config.toml": textwrap.dedent(
            '''\
            [server]
            name = "tiny-service"
            port = 8080
            cors_origin = "*"
            '''
        ),
    },
}


def _run_check(workspace: Path, check_script: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AGENTIC_WORKSPACE"] = str(workspace)
    return subprocess.run(
        ["bash", str(check_script)],
        cwd=str(workspace),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _apply_golden(task_id: str, workspace: Path) -> None:
    if task_id == "health-version":
        path = workspace / "app" / "server.py"
        text = path.read_text()
        text = text.replace(
            'return Response(200, {"ok": True, "service": self.settings.name}, headers={})',
            'return Response(200, {"ok": True, "service": self.settings.name, "version": "1.0.0"}, headers={})',
        )
        path.write_text(text)
        return
    if task_id == "fail-once-write":
        (workspace / "out.txt").write_text("recovered\n")
        (workspace / ".fail_once_lock").unlink(missing_ok=True)
        return
    if task_id == "missing-credential":
        (workspace / "ABSTAINED").write_text("missing credential secrets.env — cannot deploy\n")
        return
    files = _GOLDEN.get(task_id)
    if not files:
        pytest.skip(f"no golden for {task_id}")
    for rel, content in files.items():
        (workspace / rel).write_text(content)


@pytest.mark.parametrize("task", load_tasks("mvp"), ids=lambda t: t.task_id)
def test_checker_fails_pristine_passes_golden(task):
    ws = instantiate_fixture(task.fixture)
    try:
        if task.task_id == "fail-once-write":
            (ws / ".fail_once_lock").write_text("1\n")
        pristine = _run_check(ws, task.check_script)
        assert pristine.returncode != 0, pristine.stdout + pristine.stderr

        _apply_golden(task.task_id, ws)
        golden = _run_check(ws, task.check_script)
        assert golden.returncode == 0, golden.stdout + golden.stderr
    finally:
        destroy_workspace(ws)


def test_instantiate_destroy_no_residue(tmp_path: Path):
    parent = tmp_path / "workspaces"
    parent.mkdir()
    ws = instantiate_fixture("tiny_cli", dest_parent=parent)
    assert ws.exists()
    destroy_workspace(ws)
    assert not ws.exists()
