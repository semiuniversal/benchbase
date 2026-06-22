"""Build per-run metadata from settings and evaluation mode."""

from __future__ import annotations

from typing import Any, Literal

from benchbase.config import Settings, load_settings

EvalMode = Literal["batch", "routine", "full"]

# Full-benchmark caps for fast suites (reasoning has no cap — full dataset).
FULL_SPEED_RUNS = 10
FULL_CODING_SAMPLES = 164  # HumanEval test split
FULL_TOOL_SAMPLES = 50

BATCH_SPEED_RUNS = 3
ROUTINE_SPEED_RUNS = 5


def build_run_metadata(
    mode: EvalMode,
    runner_class: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Return run metadata for the given eval mode and suite runner."""
    settings = settings or load_settings()
    meta: dict[str, Any] = {"eval_mode": mode}

    if mode == "full":
        meta["full_benchmark"] = True
        if runner_class == "speed":
            meta["runs"] = FULL_SPEED_RUNS
        elif runner_class == "coding":
            meta["n_samples"] = FULL_CODING_SAMPLES
        elif runner_class == "tool_use":
            meta["n_samples"] = FULL_TOOL_SAMPLES
        return meta

    if mode == "batch":
        meta["batch"] = True
        sample_n = settings.batch_sample_limit
    else:
        sample_n = settings.routine_sample_limit

    if runner_class == "reasoning":
        meta["limit"] = sample_n
    elif runner_class == "coding":
        meta["n_samples"] = sample_n
    elif runner_class == "tool_use":
        meta["n_samples"] = sample_n
    elif runner_class == "speed":
        meta["runs"] = BATCH_SPEED_RUNS if mode == "batch" else ROUTINE_SPEED_RUNS

    return meta


def eval_mode_label(mode: str | None) -> str:
    if mode == "full":
        return "full benchmark (entire datasets)"
    if mode == "batch":
        return "batch quick check (sampled)"
    if mode == "routine":
        return "routine comparison (sampled)"
    return "sampled"
