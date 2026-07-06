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


def parse_litebench_pass_counts(output: str) -> tuple[int, int] | None:
    """Return (passed, total) from e.g. 'Accuracy 70.0% (7/10)'."""
    match = re.search(
        r"^\s*Accuracy\s+\d+(?:\.\d+)?%\s*\(\s*(\d+)\s*/\s*(\d+)\s*\)",
        output,
        re.I | re.MULTILINE,
    )
    if match:
        return int(match.group(1)), int(match.group(2))
    return None


def parse_litebench_accuracy(output: str) -> float | None:
    """Return accuracy as a percentage (e.g. 70.0 for 70%)."""
    # Summary table row with pass counts (most reliable).
    match = re.search(
        r"^\s*Accuracy\s+(\d+(?:\.\d+)?)\s*%\s*\(\s*\d+\s*/\s*\d+\s*\)",
        output,
        re.I | re.MULTILINE,
    )
    if match:
        return _clamp_percent(float(match.group(1)))

    counts = parse_litebench_pass_counts(output)
    if counts and counts[1] > 0:
        return _clamp_percent(counts[0] / counts[1] * 100)

    # Rich progress footer: use the last acc= (final aggregate, not per-sample).
    acc_matches = re.findall(r"acc=(\d+(?:\.\d+)?)\s*%", output, re.I)
    if acc_matches:
        return _clamp_percent(float(acc_matches[-1]))

    # Our per-sample progress lines — use the last running accuracy.
    running_matches = re.findall(
        r"\[litebench\] progress \d+/\d+ running accuracy (\d+(?:\.\d+)?)%",
        output,
        re.I,
    )
    if running_matches:
        return _clamp_percent(float(running_matches[-1]))

    return None


def resolve_litebench_score(output: str) -> float | None:
    """Prefer pass/total counts; fall back to parsed accuracy lines."""
    counts = parse_litebench_pass_counts(output)
    if counts and counts[1] > 0:
        return _clamp_percent(counts[0] / counts[1] * 100)
    return parse_litebench_accuracy(output)


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
