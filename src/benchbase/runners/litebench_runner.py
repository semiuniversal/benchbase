"""BenchBase wrapper for litebench run with configurable LiteLLM request timeout."""

from __future__ import annotations

import asyncio
import json as jsonlib
import sys
from pathlib import Path

import click
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn

from litebench.config import DB_PATH, ensure_dirs, resolve_model
from litebench.core.runner import Runner
from litebench.core.storage import Storage
from litebench.llm.client import LLMClient
from litebench.output.console import console, print_sample_failures, print_summary
from litebench.tasks import get_task, list_tasks
from litebench.tasks.arc import ARCTask
from litebench.tasks.custom import CustomTask
from litebench.tasks.mmlu import MMLUTask

from benchbase.runners.litebench_patches import apply_litebench_patches

apply_litebench_patches()


@click.group()
def main() -> None:
    """LiteBench entry point with BenchBase timeout override."""


@main.command("list")
def list_cmd() -> None:
    """List built-in tasks."""
    from litebench.output.console import print_task_list

    tasks = []
    for name in list_tasks():
        task = get_task(name)
        tasks.append((name, task.description))
    print_task_list(tasks)


@main.command()
@click.argument("task_name")
@click.option("--model", "-m", required=True)
@click.option("--samples", "-n", default=20, type=int)
@click.option("--concurrency", "-c", default=8, type=int)
@click.option("--temperature", "-t", default=0.0, type=float)
@click.option("--max-tokens", default=1024, type=int)
@click.option("--subject", default=None)
@click.option("--arc-easy", is_flag=True)
@click.option("--split", default="test")
@click.option("--json-out", type=click.Path(path_type=Path), default=None)
@click.option("--no-save", is_flag=True)
@click.option(
    "--timeout",
    default=None,
    type=int,
    help="LiteLLM per-request timeout in seconds (overrides default).",
)
def run(
    task_name: str,
    model: str,
    samples: int,
    concurrency: int,
    temperature: float,
    max_tokens: int,
    subject: str | None,
    arc_easy: bool,
    split: str,
    json_out: Path | None,
    no_save: bool,
    timeout: int | None,
) -> None:
    """Run a litebench task (same as litebench run, with --timeout support)."""
    from benchbase.config import load_settings

    ensure_dirs()
    resolved = resolve_model(model)
    llm_timeout = timeout if timeout is not None else load_settings().litebench_timeout_seconds

    task_path = Path(task_name)
    if task_path.exists() and task_path.suffix.lower() in {".yaml", ".yml"}:
        task = CustomTask(task_path)
    elif task_name.lower() == "mmlu" and subject:
        task = MMLUTask(subject=subject)
    elif task_name.lower() == "arc" and arc_easy:
        task = ARCTask(config="ARC-Easy")
    else:
        try:
            task = get_task(task_name)
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            sys.exit(1)

    console.print(f"Loading [cyan]{task.name}[/] samples...")
    sample_list = list(task.load_samples(n=samples, split=split))
    if not sample_list:
        console.print("[red]No samples loaded.[/]")
        sys.exit(1)
    console.print(
        f"Loaded [bold]{len(sample_list)}[/] samples. Running on [cyan]{resolved}[/] "
        f"(timeout={llm_timeout}s)..."
    )

    client = LLMClient(
        model=resolved,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=llm_timeout,
    )

    async def _go() -> None:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("acc={task.fields[acc]}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            pid = progress.add_task("Running", total=len(sample_list), acc="—")
            correct = 0

            def on_progress(done: int, total: int, result):
                nonlocal correct
                if result.correct:
                    correct += 1
                progress.update(pid, completed=done, acc=f"{correct / done * 100:.1f}%")

            runner = Runner(
                task=task, client=client, concurrency=concurrency, on_progress=on_progress
            )
            summary, results = await runner.run(sample_list)

        if not no_save:
            storage = Storage(DB_PATH)
            await storage.init()
            await storage.save_run(summary, results)

        print_summary(summary)
        print_sample_failures(results)

        if json_out:
            payload = {
                "summary": summary.model_dump(mode="json"),
                "results": [r.model_dump(mode="json") for r in results],
            }
            json_out.parent.mkdir(parents=True, exist_ok=True)
            json_out.write_text(jsonlib.dumps(payload, indent=2, ensure_ascii=False))
            console.print(f"[dim]Per-sample results → {json_out}[/]")

    asyncio.run(_go())


if __name__ == "__main__":
    main()
