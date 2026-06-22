"""Helpers for per-run metadata overrides (e.g. batch quick runs)."""

from __future__ import annotations

import json

from benchbase.db.models import Run


def parse_run_metadata(run: Run) -> dict:
    if not run.metadata_json:
        return {}
    try:
        return json.loads(run.metadata_json)
    except json.JSONDecodeError:
        return {}


def is_full_benchmark(run: Run) -> bool:
    return bool(parse_run_metadata(run).get("full_benchmark"))


def metadata_int(run: Run, key: str, suite_config: dict, default: int) -> int:
    meta = parse_run_metadata(run)
    if key in meta and meta[key] is not None:
        return int(meta[key])
    return int(suite_config.get(key, default))


def metadata_optional_int(run: Run, key: str, suite_config: dict) -> int | None:
    """Return an int override when set on the run or suite; otherwise None."""
    if key == "limit" and is_full_benchmark(run):
        return None
    meta = parse_run_metadata(run)
    if key in meta and meta[key] is not None:
        return int(meta[key])
    if key in suite_config and suite_config[key] is not None:
        return int(suite_config[key])
    return None
