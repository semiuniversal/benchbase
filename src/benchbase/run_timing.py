"""Live timing and ETA for in-flight benchmark runs."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from benchbase.benchmark_duration import format_duration_range, format_duration_seconds

_PROGRESS_RE = re.compile(r"(?<![\d.])(\d{1,5})/(\d{1,5})(?![\d.])")
_PERCENT_RE = re.compile(r"(\d{1,3})%")


def active_seconds_from_metadata(meta: dict[str, Any] | None) -> float:
    """Persisted active work time (ms); excludes paused / idle wall time."""
    if not meta:
        return 0.0
    raw = meta.get("active_ms")
    if raw is None:
        return 0.0
    try:
        return max(0.0, float(raw) / 1000.0)
    except (TypeError, ValueError):
        return 0.0


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
    estimate_source: str = "static"
    active_base_sec: float = 0.0

    def __post_init__(self) -> None:
        if self.work_units_total <= 0:
            self.work_units_total = 1


class RunTimingTracker:
    _states: dict[int, RunTimingState] = {}

    @classmethod
    def _active_elapsed(cls, state: RunTimingState) -> float:
        return state.active_base_sec + max(0.0, time.monotonic() - state.started_at)

    @classmethod
    def start(
        cls,
        run_id: int,
        runner_class: str,
        estimate: dict[str, Any],
        *,
        active_base_sec: float = 0.0,
    ) -> None:
        cls._states[run_id] = RunTimingState(
            runner_class=runner_class,
            started_at=time.monotonic(),
            work_units_total=int(estimate.get("work_units_total", 1)),
            estimate_seconds_low=float(estimate.get("estimate_seconds_low", 0)),
            estimate_seconds_high=float(estimate.get("estimate_seconds_high", 0)),
            estimate_source=str(estimate.get("estimate_source", "static")),
            active_base_sec=max(0.0, float(active_base_sec)),
        )

    @classmethod
    def sync_active_base(cls, run_id: int, active_base_sec: float) -> None:
        """Never shrink below in-memory base (DB active_ms lags until pause)."""
        state = cls._states.get(run_id)
        if state:
            state.active_base_sec = max(
                state.active_base_sec,
                max(0.0, float(active_base_sec)),
            )

    @classmethod
    def record_item(cls, run_id: int, *, latency_ms: float | None = None) -> None:
        """Update running average after each scored item (model-specific live pace)."""
        state = cls._states.get(run_id)
        if not state:
            return
        state.work_units_done += 1
        state.progress_label = f"{state.work_units_done}/{state.work_units_total}"
        sec: float | None = None
        if latency_ms is not None and latency_ms > 0:
            sec = latency_ms / 1000.0
        if sec is None and state.work_units_done > 0:
            sec = cls._active_elapsed(state) / state.work_units_done
        if sec is None or sec <= 0:
            return
        if state.calibrated_sec_per_unit is None:
            state.calibrated_sec_per_unit = sec
        else:
            # EMA: bias toward recent items on slow axes (BFCL, coding).
            state.calibrated_sec_per_unit = 0.75 * state.calibrated_sec_per_unit + 0.25 * sec

    @classmethod
    def attach_running(
        cls,
        run_id: int,
        runner_class: str,
        estimate: dict[str, Any],
        *,
        done: int,
        total: int,
        active_elapsed_sec: float | None = None,
    ) -> None:
        """Rebuild in-memory state after process restart (API polling / log modal)."""
        if cls._states.get(run_id):
            cls.sync_progress(
                run_id,
                done,
                total,
                active_elapsed_sec=active_elapsed_sec,
            )
            if active_elapsed_sec is not None:
                cls.sync_active_base(run_id, active_elapsed_sec)
            return
        cls._states[run_id] = RunTimingState(
            runner_class=runner_class,
            started_at=time.monotonic(),
            work_units_total=max(1, int(total)),
            estimate_seconds_low=float(estimate.get("estimate_seconds_low", 0)),
            estimate_seconds_high=float(estimate.get("estimate_seconds_high", 0)),
            estimate_source=str(estimate.get("estimate_source", "static")),
            work_units_done=max(0, int(done)),
            progress_label=f"{done}/{max(1, int(total))}" if total > 0 else None,
            active_base_sec=max(0.0, float(active_elapsed_sec or 0)),
        )
        state = cls._states[run_id]
        if done >= 1 and active_elapsed_sec and active_elapsed_sec > 0:
            state.calibrated_sec_per_unit = active_elapsed_sec / done

    @classmethod
    def sync_progress(
        cls,
        run_id: int,
        done: int,
        total: int,
        *,
        active_elapsed_sec: float | None = None,
    ) -> None:
        """Reconcile in-memory counters with DB item count (e.g. polling / resume)."""
        state = cls._states.get(run_id)
        if not state or total < 1:
            return
        state.work_units_total = max(state.work_units_total, total)
        state.work_units_done = max(state.work_units_done, done)
        state.progress_label = f"{state.work_units_done}/{state.work_units_total}"
        if active_elapsed_sec is not None and active_elapsed_sec > 0:
            state.active_base_sec = max(state.active_base_sec, active_elapsed_sec)
        if active_elapsed_sec and active_elapsed_sec > 0 and state.work_units_done >= 1:
            state.calibrated_sec_per_unit = active_elapsed_sec / state.work_units_done
        elif state.work_units_done >= 1:
            active = cls._active_elapsed(state)
            if active > 0.01:
                state.calibrated_sec_per_unit = active / state.work_units_done

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
            if total >= state.work_units_total or state.work_units_done == 0:
                state.work_units_total = total
                state.work_units_done = done
                state.progress_label = f"{done}/{total}"
                active = cls._active_elapsed(state)
                if done >= 1 and active > 0.01:
                    state.calibrated_sec_per_unit = active / done

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
        del started_at_wall  # wall clock intentionally ignored (pause / overnight idle)
        state = cls._states.get(run_id)
        if not state:
            return None

        elapsed = cls._active_elapsed(state)

        eta_seconds: float | None = None
        eta_label: str | None = None
        progress_percent: float | None = None
        estimate_label: str

        if state.work_units_done > 0 and state.work_units_total > 0:
            progress_percent = min(
                99.0,
                100.0 * state.work_units_done / state.work_units_total,
            )

        if state.calibrated_sec_per_unit and state.work_units_done >= 1:
            projected_total = state.calibrated_sec_per_unit * state.work_units_total
            estimate_label = format_duration_seconds(projected_total)
            if state.work_units_done < state.work_units_total:
                remaining_units = state.work_units_total - state.work_units_done
                eta_seconds = remaining_units * state.calibrated_sec_per_unit
                eta_label = f"{format_duration_seconds(eta_seconds)} remaining (this axis)"
        else:
            estimate_label = format_duration_range(
                state.estimate_seconds_low,
                state.estimate_seconds_high,
            )
            if elapsed > 5 and state.estimate_seconds_high > 0:
                mid = (state.estimate_seconds_low + state.estimate_seconds_high) / 2
                if elapsed < mid * 1.5:
                    eta_seconds = max(0, mid - elapsed)
                    eta_label = f"~{format_duration_seconds(eta_seconds)} remaining (prior)"

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
            "sec_per_item": round(state.calibrated_sec_per_unit, 2)
            if state.calibrated_sec_per_unit
            else None,
            "estimate_source": state.estimate_source,
        }