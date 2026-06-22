"""Live timing and ETA for in-flight benchmark runs."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from benchbase.benchmark_duration import format_duration_range, format_duration_seconds

_PROGRESS_RE = re.compile(r"(?<![\d.])(\d{1,5})/(\d{1,5})(?![\d.])")
_PERCENT_RE = re.compile(r"(\d{1,3})%")


@dataclass
class RunTimingState:
    runner_class: str
    started_at: float
    work_units_total: int
    estimate_seconds_low: float
    estimate_seconds_high: float
    work_units_done: int = 0
    progress_label: str | None = None
    calibrated_sec_per_unit: float | None = None

    def __post_init__(self) -> None:
        if self.work_units_total <= 0:
            self.work_units_total = 1


class RunTimingTracker:
    _states: dict[int, RunTimingState] = {}

    @classmethod
    def start(
        cls,
        run_id: int,
        runner_class: str,
        estimate: dict[str, Any],
    ) -> None:
        cls._states[run_id] = RunTimingState(
            runner_class=runner_class,
            started_at=time.monotonic(),
            work_units_total=int(estimate.get("work_units_total", 1)),
            estimate_seconds_low=float(estimate.get("estimate_seconds_low", 0)),
            estimate_seconds_high=float(estimate.get("estimate_seconds_high", 0)),
        )

    @classmethod
    def clear(cls, run_id: int) -> None:
        cls._states.pop(run_id, None)

    @classmethod
    def clear_all(cls) -> None:
        cls._states.clear()

    @classmethod
    def on_log_line(cls, run_id: int, text: str) -> None:
        state = cls._states.get(run_id)
        if not state or not text:
            return

        for match in _PROGRESS_RE.finditer(text):
            done, total = int(match.group(1)), int(match.group(2))
            if total < 2 or done > total:
                continue
            # Prefer the largest total (litebench rich bar) over spurious ratios.
            if total >= state.work_units_total or state.work_units_done == 0:
                state.work_units_total = total
                state.work_units_done = done
                state.progress_label = f"{done}/{total}"
                elapsed = time.monotonic() - state.started_at
                if done >= 2:
                    state.calibrated_sec_per_unit = elapsed / done

        pct_match = _PERCENT_RE.search(text)
        if pct_match and state.work_units_total > 1:
            pct = min(100, int(pct_match.group(1)))
            if pct > 0:
                done = max(state.work_units_done, int(state.work_units_total * pct / 100))
                state.work_units_done = done
                state.progress_label = f"{pct}%"

    @classmethod
    def status(
        cls,
        run_id: int,
        started_at_wall: float | None = None,
    ) -> dict[str, Any] | None:
        state = cls._states.get(run_id)
        if not state:
            return None

        now = time.monotonic()
        elapsed = now - state.started_at
        if started_at_wall is not None:
            elapsed = max(elapsed, time.time() - started_at_wall)

        estimate_label = format_duration_range(
            state.estimate_seconds_low,
            state.estimate_seconds_high,
        )

        eta_seconds: float | None = None
        eta_label: str | None = None
        progress_percent: float | None = None

        if state.work_units_done > 0 and state.work_units_total > 0:
            progress_percent = min(
                99.0,
                100.0 * state.work_units_done / state.work_units_total,
            )

        if (
            state.calibrated_sec_per_unit
            and state.work_units_done >= 2
            and state.work_units_done < state.work_units_total
        ):
            remaining_units = state.work_units_total - state.work_units_done
            eta_seconds = remaining_units * state.calibrated_sec_per_unit
            eta_label = f"{format_duration_seconds(eta_seconds)} remaining"
        elif elapsed > 5 and state.estimate_seconds_high > 0:
            mid = (state.estimate_seconds_low + state.estimate_seconds_high) / 2
            if elapsed < state.estimate_seconds_high:
                eta_seconds = max(0, mid - elapsed)
                eta_label = f"~{format_duration_seconds(eta_seconds)} remaining (estimated)"
                progress_percent = min(
                    99.0,
                    100.0 * elapsed / state.estimate_seconds_high,
                )

        return {
            "elapsed_seconds": round(elapsed, 1),
            "elapsed_label": format_duration_seconds(elapsed).replace("~", ""),
            "estimate_label": estimate_label,
            "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
            "eta_label": eta_label,
            "progress_percent": round(progress_percent, 1) if progress_percent else None,
            "progress_label": state.progress_label,
            "work_units_done": state.work_units_done,
            "work_units_total": state.work_units_total,
        }
