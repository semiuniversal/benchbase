"""CLI entry point for BenchBase."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer
import uvicorn
from rich.console import Console

from benchbase.server_process import (
    DEFAULT_PORT,
    clear_state,
    ensure_single_server,
    kill_port_listeners,
    read_state,
    status_message,
    stop_registered_server,
    write_state,
)

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


def _init_db_sync() -> None:
    """Run the async DB init in a one-shot event loop."""
    import asyncio
    from benchbase.db.session import init_db

    asyncio.run(init_db())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(DEFAULT_PORT, help="Bind port (default 8000 — use this port in the browser)"),
    reload: bool = typer.Option(
        True,
        "--reload/--no-reload",
        help="Auto-reload Python on code changes (default on for development)",
    ),
    skip_build: bool = typer.Option(False, "--skip-build", help="Skip the frontend build step"),
):
    """Start the one BenchBase server (stops any previous instance first)."""
    for line in ensure_single_server(port):
        console.print(f"[yellow]{line}[/yellow]")

    _build_frontend(skip_build)

    for pid in kill_port_listeners(port):
        console.print(f"[yellow]Stopped process {pid} on port {port}[/yellow]")

    console.print("[bold]Initialising database…[/bold]")
    _init_db_sync()

    write_state(port, os.getpid())
    url = f"http://127.0.0.1:{port}" if host in ("0.0.0.0", "::") else f"http://{host}:{port}"
    console.print(f"[bold green]Starting BenchBase on {url}[/bold green]")
    console.print(
        "[dim]One server only — re-run `uv run benchbase serve` to replace this process. "
        "Use `benchbase status` / `benchbase stop`.[/dim]"
    )

    try:
        uvicorn.run(
            "benchbase.main:app",
            host=host,
            port=port,
            reload=reload,
        )
    finally:
        state = read_state()
        if state and int(state.get("pid", 0)) == os.getpid():
            clear_state()


@app.command()
def status():
    """Show whether BenchBase is running and which URL to use."""
    console.print(status_message())


@app.command()
def stop(
    port: int = typer.Option(DEFAULT_PORT, help="Port to clear if listeners remain"),
):
    """Stop the running BenchBase server."""
    old_pid, old_port, killed = stop_registered_server()
    extra = kill_port_listeners(port)
    all_pids = set(killed) | set(extra)

    if old_pid:
        console.print(f"[green]Stopped BenchBase server (was pid {old_pid}, port {old_port})[/green]")
    for pid in sorted(all_pids):
        if pid != old_pid:
            console.print(f"[green]Stopped process {pid} on port {port}[/green]")

    if not old_pid and not all_pids:
        console.print("[dim]No BenchBase server was running.[/dim]")


@app.command()
def version():
    """Print the current version."""
    from benchbase import __version__

    typer.echo(f"benchbase {__version__}")


if __name__ == "__main__":
    app()
