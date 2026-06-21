"""CLI entry point for BenchBase."""

from __future__ import annotations

import os
import signal
import shutil
import subprocess
import sys
from pathlib import Path

import typer
import uvicorn
from rich.console import Console

app = typer.Typer(name="benchbase", help="Local LLM Benchmark Dashboard")
console = Console()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"


def _find_npm() -> str | None:
    """Locate npm, checking nvm paths if the default lookup fails."""
    npm = shutil.which("npm")
    if npm:
        return npm
    nvm_dir = os.environ.get("NVM_DIR", Path.home() / ".nvm")
    default_bin = Path(nvm_dir) / "alias" / "default"
    if not default_bin.exists():
        for candidate in sorted(Path(nvm_dir, "versions", "node").glob("*/bin/npm")):
            return str(candidate)
    return None


def _build_frontend(skip_build: bool) -> None:
    if skip_build:
        if FRONTEND_DIST.is_dir():
            console.print("[dim]--skip-build: using existing frontend/dist[/dim]")
            return
        console.print("[yellow]--skip-build set but frontend/dist missing; building anyway[/yellow]")

    if not (FRONTEND_DIR / "package.json").exists():
        console.print("[yellow]frontend/package.json not found – skipping frontend build[/yellow]")
        return

    npm = _find_npm()
    if not npm:
        console.print("[yellow]npm not found – skipping frontend build[/yellow]")
        return

    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.is_dir():
        console.print("[bold]Installing frontend dependencies…[/bold]")
        subprocess.run([npm, "ci"], cwd=FRONTEND_DIR, check=True)

    console.print("[bold]Building frontend…[/bold]")
    subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR, check=True)
    console.print("[green]Frontend build complete[/green]")


def _kill_port(port: int) -> None:
    """Kill any process already listening on the given TCP port."""
    try:
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"],
            capture_output=True, text=True,
        )
        pids = [int(p) for p in out.stdout.strip().split() if p.isdigit()]
    except FileNotFoundError:
        # lsof unavailable – try ss + awk fallback
        try:
            out = subprocess.run(
                ["ss", "-tlnp", f"sport = :{port}"],
                capture_output=True, text=True,
            )
            pids = []
            for line in out.stdout.splitlines():
                if f":{port}" in line and "pid=" in line:
                    for segment in line.split(","):
                        if segment.startswith("pid="):
                            pids.append(int(segment.split("=")[1]))
        except FileNotFoundError:
            return

    own_pid = os.getpid()
    for pid in set(pids):
        if pid == own_pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            console.print(f"[yellow]Killed stale process {pid} on port {port}[/yellow]")
        except ProcessLookupError:
            pass


def _init_db_sync() -> None:
    """Run the async DB init in a one-shot event loop."""
    import asyncio
    from benchbase.db.session import init_db

    asyncio.run(init_db())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, help="Enable auto-reload for development"),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip the frontend build step"),
):
    """Build the frontend, clear the port, prep the DB, and start the server."""
    _build_frontend(skip_build)
    _kill_port(port)

    console.print("[bold]Initialising database…[/bold]")
    _init_db_sync()

    console.print(f"[bold green]Starting BenchBase on http://{host}:{port}[/bold green]")
    uvicorn.run(
        "benchbase.main:app",
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def version():
    """Print the current version."""
    from benchbase import __version__

    typer.echo(f"benchbase {__version__}")


if __name__ == "__main__":
    app()
