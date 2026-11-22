"""Live ETA from running average × remaining items."""

from __future__ import annotations

import time

import pytest

from benchbase.run_timing import RunTimingTracker


def test_eta_after_first_item():
    RunTimingTracker.clear_all()
    run_id = 99
    RunTimingTracker.start(
        run_id,
        "coding",
        {
            "work_units_total": 40,
            "estimate_seconds_low": 100,
            "estimate_seconds_high": 800,
            "estimate_source": "static",
        },
    )
    RunTimingTracker.record_item(run_id, latency_ms=120_000)
    st = RunTimingTracker.status(run_id)
    assert st is not None
    assert st["work_units_done"] == 1
    assert st["eta_seconds"] is not None
    assert st["eta_seconds"] > 0
    assert "remaining" in (st["eta_label"] or "")


def test_attach_running_uses_wall_pace():
    RunTimingTracker.clear_all()
    run_id = 101
    RunTimingTracker.attach_running(
        run_id,
        "coding",
        {"work_units_total": 40, "estimate_seconds_low": 100, "estimate_seconds_high": 800},
        done=20,
        total=40,
        wall_elapsed_sec=800.0,
    )
    st = RunTimingTracker.status(run_id)
    assert st is not None
    assert st["work_units_done"] == 20
    assert st["progress_percent"] == pytest.approx(50.0, abs=0.2)
    assert st["sec_per_item"] == pytest.approx(40.0, abs=0.1)
    assert st["eta_seconds"] == pytest.approx(40.0 * 20, rel=0.05)


def test_sync_progress_sets_pace():
    RunTimingTracker.clear_all()
    run_id = 100
    RunTimingTracker.start(
        run_id,
        "tool_use",
        {"work_units_total": 10, "estimate_seconds_low": 50, "estimate_seconds_high": 500},
    )
    time.sleep(0.05)
    RunTimingTracker.sync_progress(run_id, 3, 10)
    st = RunTimingTracker.status(run_id)
    assert st is not None
    assert st["work_units_done"] == 3
    assert st["sec_per_item"] is not None
    assert st["eta_seconds"] == pytest.approx(st["sec_per_item"] * 7, rel=0.3)