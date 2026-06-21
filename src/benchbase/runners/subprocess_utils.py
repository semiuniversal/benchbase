"""Shared async subprocess helpers for benchmark runners."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 1800  # 30 minutes


@dataclass
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


async def run_tool(
    args: list[str],
    *,
    timeout: int = DEFAULT_TIMEOUT,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> SubprocessResult:
    """Run a CLI tool asynchronously and capture its output.

    Returns a SubprocessResult with stdout, stderr, return code, and timeout flag.
    """
    logger.info("Running: %s", " ".join(args))

    import os
    merged_env = {**os.environ, **(env or {})}

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        env=merged_env,
    )

    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        stdout_bytes, stderr_bytes = await proc.communicate()

    result = SubprocessResult(
        returncode=proc.returncode or -1,
        stdout=stdout_bytes.decode(errors="replace"),
        stderr=stderr_bytes.decode(errors="replace"),
        timed_out=timed_out,
    )

    if timed_out:
        logger.error("Tool timed out after %ds: %s", timeout, " ".join(args))
    elif result.returncode != 0:
        logger.error(
            "Tool exited %d: %s\nstderr: %s",
            result.returncode, " ".join(args), result.stderr[:500],
        )

    return result


def make_temp_dir(prefix: str = "benchbase_") -> Path:
    """Create a temporary directory for tool output."""
    return Path(tempfile.mkdtemp(prefix=prefix))
