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
    if port != DEFAULT_PORT:
        console.print(
            f"[yellow]Note: port {port} is not the default ({DEFAULT_PORT}). "
            f"Open {url} in the browser — not localhost:{DEFAULT_PORT}.[/yellow]"
        )
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


@app.command("rescore-speed")
def rescore_speed(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write nulls to the database (default is dry-run)",
    ),
):
    """Invalidate collapsed historical Speed/Prefill tok/s. Does not invent replacements."""
    import asyncio

    from benchbase.db.session import get_session_factory, init_db
    from benchbase.speed_rescore import rescore_speed_history

    async def _go() -> dict:
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            return await rescore_speed_history(db, apply=apply)

    report = asyncio.run(_go())
    actions = report.get("actions") or []
    if not actions:
        console.print("[dim]No collapsed Speed/Prefill scores to invalidate.[/dim]")
        return

    mode = "APPLY" if apply else "DRY-RUN"
    console.print(f"[bold]{mode}: {len(actions)} Speed cell(s) fail the short-EOS / collapsed-prefill gate[/bold]")
    for action in actions:
        old = action.get("old_score")
        old_s = f"{old:.4g}" if isinstance(old, (int, float)) else str(old)
        console.print(
            f"  run={action.get('run_id')} model={action.get('model')} "
            f"task={action.get('task_name')} old={old_s} reason={action.get('reason')}"
        )

    models = report.get("models_needing_rerun") or []
    if models:
        console.print("[yellow]Models that need a Speed re-run for comparable tok/s:[/yellow]")
        for name in models:
            console.print(f"  - {name}")

    if apply:
        console.print(f"[green]Wrote {report.get('written', 0)} row(s). Compare will skip null Speed/Prefill.[/green]")
    else:
        console.print("[dim]Dry-run only. Pass --apply to null these scores.[/dim]")


@app.command("rescore-work-clock")
def rescore_work_clock_cmd(
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Stamp invalid_reason on contaminated groups (default is dry-run)",
    ),
):
    """Print derived work-clock (sec/correct) from existing Standard/Smoke sittings."""
    import asyncio

    from benchbase.db.session import get_session_factory, init_db
    from benchbase.work_clock import rescore_work_clock

    async def _go() -> dict:
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            return await rescore_work_clock(db, apply=apply)

    report = asyncio.run(_go())
    rows = report.get("sittings") or []
    mode = "APPLY" if apply else "DRY-RUN"
    if not rows:
        console.print("[dim]No complete quality sittings for work clock.[/dim]")
        return

    console.print(f"[bold]{mode}: {len(rows)} quality sitting(s)[/bold]")
    for row in rows:
        flag = "SELECTED" if row.get("selected") else "       "
        sec = row.get("sec_per_correct")
        sec_s = f"{sec:.2f}s/correct" if isinstance(sec, (int, float)) else "—"
        wall = row.get("suite_wall_s")
        wall_s = f"{wall:.0f}s" if isinstance(wall, (int, float)) else "—"
        extra = ""
        if row.get("contaminated"):
            extra = f" CONTAMINATED ({row.get('invalid_reason')})"
        elif row.get("work_clock_tier") == "smoke":
            extra = " smoke"
        console.print(
            f"  {flag} group={row.get('run_group_id')} model={row.get('model')} "
            f"tier={row.get('work_clock_tier')} wall={wall_s} "
            f"n_correct={row.get('n_correct')} {sec_s}{extra}"
        )

    if apply:
        console.print(
            f"[green]Wrote invalid_reason on {report.get('written', 0)} contaminated run(s).[/green]"
        )
    else:
        console.print(
            "[dim]Dry-run only. Numbers are derived on scorecard read. "
            "[dim]Dry-run only. Pass --apply to stamp contaminated group metadata.[/dim]"
        )


@app.command("probe-litellm")
def probe_litellm_cmd(
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model id to probe (default: first model from /v1/models)",
    ),
):
    """Verify LiteLLM quality route has no sticky min_tokens on extra_body."""
    import asyncio

    from benchbase.litellm_probe import probe_litellm_quality_route

    report = asyncio.run(probe_litellm_quality_route(model=model))
    base = report.get("base_url") or "?"
    probe_model = report.get("model") or "?"
    if report.get("sticky_min_tokens"):
        console.print(
            f"[red]FAIL[/red] sticky min_tokens on quality route "
            f"({base}, model={probe_model})"
        )
        console.print(f"  {report.get('detail', '')}")
        raise typer.Exit(code=1)
    if not report.get("ok"):
        console.print(
            f"[yellow]WARN[/yellow] probe did not pass ({base}, model={probe_model})"
        )
        console.print(f"  {report.get('detail', '')}")
        raise typer.Exit(code=1)
    console.print(
        f"[green]OK[/green] quality route accepts max_tokens=1 "
        f"({base}, model={probe_model})"
    )


controls_app = typer.Typer(help="Negative scoring controls (null/random/echo)")
app.add_typer(controls_app, name="controls")


@controls_app.command("run")
def controls_run(
    tier: str = typer.Option("standard", help="smoke|standard|thorough"),
):
    """Run null/random/echo controls and update scorer-invalid gates."""
    import asyncio

    from benchbase.controls import run_controls
    from benchbase.db.models import RunTier
    from benchbase.db.session import get_session_factory, init_db

    async def _go() -> dict:
        await init_db()
        factory = get_session_factory()
        async with factory() as db:
            return await run_controls(db, tier=RunTier(tier))

    report = asyncio.run(_go())
    console.print_json(data=report)
    if not report.get("all_valid"):
        console.print("[red]One or more suites failed control bounds (scorer-invalid).[/red]")
        raise typer.Exit(code=1)
    console.print("[green]All control bounds passed.[/green]")


if __name__ == "__main__":
    app()
