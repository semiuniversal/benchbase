"""Parse LiteBench CLI output for accuracy and error counts."""

from __future__ import annotations

import re


def _clamp_percent(value: float) -> float:
    """LiteBench reports accuracy as 0–100%; guard against stray digit parses."""
    if value < 0:
        return 0.0
    if value > 100:
        return 100.0
    return value


def parse_litebench_accuracy(output: str) -> float | None:
    """Return accuracy as a percentage (e.g. 70.0 for 70%)."""
    # Summary table row (most reliable).
    match = re.search(r"Accuracy\s+(\d+(?:\.\d+)?)\s*%", output, re.I)
    if match:
        return _clamp_percent(float(match.group(1)))

    # Rich progress line: acc=70.0%
    match = re.search(r"acc=(\d+(?:\.\d+)?)\s*%", output, re.I)
    if match:
        return _clamp_percent(float(match.group(1)))

    # Fallback labels.
    match = re.search(
        r"(?:accuracy|pass_rate|success(?:\s+rate)?|score)[:\s=]+(\d+(?:\.\d+)?)\s*%?",
        output,
        re.I,
    )
    if match:
        value = float(match.group(1))
        if value <= 1.0:
            value *= 100
        return _clamp_percent(value)

    return None


def parse_litebench_pass_counts(output: str) -> tuple[int, int] | None:
    """Return (passed, total) from e.g. 'Accuracy 70.0% (7/10)'."""
    match = re.search(
        r"Accuracy\s+\d+(?:\.\d+)?%\s*\((\d+)\s*/\s*(\d+)\)",
        output,
        re.I,
    )
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def count_litebench_backend_errors(output: str) -> int:
    """Count obvious upstream inference failures in litebench output."""
    lowered = output.lower()
    patterns = (
        "cuda prefill failed",
        "badrequesterror",
        "context length",
        "out of memory",
    )
    return sum(lowered.count(p) for p in patterns)
