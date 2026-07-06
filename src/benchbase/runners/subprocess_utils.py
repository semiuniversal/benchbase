"""Shared async subprocess helpers for benchmark runners."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from benchbase.run_controller import (
    is_cancelled,
    kill_subprocess,
    register_subprocess,
    unregister_subprocess,
)
from benchbase.run_log import RunLogManager, run_log_context

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 1800  # 30 minutes
_POLL_INTERVAL = 0.5

# llama-benchy uses HuggingFace tokenizers only to count prompt tokens — not PyTorch models.
# These env vars keep transformers/huggingface from printing scary but irrelevant stderr.
BENCHMARK_TOOL_ENV: dict[str, str] = {
    "PYTHONUNBUFFERED": "1",
    "TRANSFORMERS_VERBOSITY": "error",
    "HUGGINGFACE_HUB_VERBOSITY": "error",
    "TOKENIZERS_PARALLELISM": "false",
}

# Harmless stderr from transformers/tokenizers when benchmarking via API (no local model weights).
_STDERR_NOISE_MARKERS = (
    "PyTorch was not found",
    "unauthenticated requests to the HF Hub",
)


def _is_stderr_noise(text: str) -> bool:
    return any(marker in text for marker in _STDERR_NOISE_MARKERS)


@dataclass
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False


async def _pump_stream(
    stream: asyncio.StreamReader | None,
    chunks: list[str],
    run_id: int | None,
    label: str,
) -> None:
    if stream is None:
        return

    pending = ""
    while True:
        data = await stream.read(4096)
        if not data:
            break
        pending += data.decode(errors="replace")
        while pending:
            nl_idx = pending.find("\n")
            cr_idx = pending.find("\r")
            if nl_idx == -1 and cr_idx == -1:
                break

            if nl_idx != -1 and (cr_idx == -1 or nl_idx <= cr_idx):
                line, pending = pending[: nl_idx + 1], pending[nl_idx + 1 :]
            elif cr_idx != -1:
                line, pending = pending[: cr_idx + 1], pending[cr_idx + 1 :]
                if not line.endswith("\n"):
                    line = line.rstrip("\r") + "\n"
            else:
                break

            chunks.append(line)
            if run_id is not None and label == "stderr" and _is_stderr_noise(line):
                continue
            if run_id is not None:
                RunLogManager.append(run_id, line, stream=label)

    if pending:
        text = pending if pending.endswith("\n") else pending + "\n"
        chunks.append(text)
        if run_id is not None and not (label == "stderr" and _is_stderr_noise(text)):
            RunLogManager.append(run_id, text, stream=label)


async def _wait_for_proc(
    proc: asyncio.subprocess.Process,
    *,
    timeout: int,
    run_id: int | None,
) -> str:
    """Wait for subprocess exit, polling for user cancellation."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    while True:
        if run_id is not None and is_cancelled(run_id):
            kill_subprocess(proc)
            await proc.wait()
            return "cancelled"

        if proc.returncode is not None:
            return "done"

        remaining = deadline - loop.time()
        if remaining <= 0:
            kill_subprocess(proc)
            await proc.wait()
            return "timeout"

        try:
            await asyncio.wait_for(proc.wait(), timeout=min(_POLL_INTERVAL, remaining))
            return "done"
        except asyncio.TimeoutError:
            continue


async def _cleanup_stream_tasks(
    stdout_task: asyncio.Task,
    stderr_task: asyncio.Task,
) -> None:
    for task in (stdout_task, stderr_task):
        if not task.done():
            task.cancel()
    await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)


async def run_tool(
    args: list[str],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    run_id: int | None = None,
) -> SubprocessResult:
    """Run a CLI tool asynchronously, streaming output to the run log when configured."""
    effective_run_id = run_id if run_id is not None else run_log_context.get()
    cmd = " ".join(args)
    logger.info("Running: %s", cmd)
    if effective_run_id is not None:
        RunLogManager.log(effective_run_id, f"$ {cmd}")

    import os
    merged_env = {**os.environ, **BENCHMARK_TOOL_ENV, **(env or {})}

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=merged_env,
        start_new_session=True,
    )

    if effective_run_id is not None:
        register_subprocess(effective_run_id, proc)

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    timed_out = False
    cancelled = False

    stdout_task = asyncio.create_task(
        _pump_stream(proc.stdout, stdout_chunks, effective_run_id, "stdout")
    )
    stderr_task = asyncio.create_task(
        _pump_stream(proc.stderr, stderr_chunks, effective_run_id, "stderr")
    )

    try:
        outcome = await _wait_for_proc(proc, timeout=timeout, run_id=effective_run_id)
        timed_out = outcome == "timeout"
        cancelled = outcome == "cancelled" or (
            effective_run_id is not None and is_cancelled(effective_run_id)
        )
    except asyncio.CancelledError:
        kill_subprocess(proc)
        await proc.wait()
        cancelled = True
        raise
    finally:
        await _cleanup_stream_tasks(stdout_task, stderr_task)
        if effective_run_id is not None:
            unregister_subprocess(effective_run_id)

    result = SubprocessResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout="".join(stdout_chunks),
        stderr="".join(stderr_chunks),
        timed_out=timed_out,
        cancelled=cancelled,
    )

    if cancelled:
        logger.info("Tool cancelled: %s", cmd)
        if effective_run_id is not None:
            RunLogManager.log(effective_run_id, "[cancelled by user]")
    elif timed_out:
        logger.error("Tool timed out after %ds: %s", timeout, cmd)
        if effective_run_id is not None:
            RunLogManager.log(effective_run_id, f"[timed out after {timeout}s]")
    elif result.returncode != 0:
        logger.error(
            "Tool exited %d: %s\nstderr: %s",
            result.returncode, cmd, result.stderr[:500],
        )

    return result


def make_temp_dir(prefix: str = "benchbase_") -> Path:
    """Create a temporary directory for tool output."""
    return Path(tempfile.mkdtemp(prefix=prefix))
