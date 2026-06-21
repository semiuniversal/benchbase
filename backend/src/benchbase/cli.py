"""CLI entry point for BenchBase."""

import typer
import uvicorn

app = typer.Typer(name="benchbase", help="Local LLM Benchmark Dashboard")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, help="Enable auto-reload for development"),
):
    """Start the BenchBase API server."""
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
