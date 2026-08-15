"""Speed index vs a local work-clock reference (display-time, not persisted)."""

from __future__ import annotations

from benchbase.work_clock import attach_speed_indexes, compute_speed_index


def _clock(*, sec: float, n: int = 400, tier: str = "standard", reason: str | None = None):
    return {
        "sec_per_correct": sec,
        "n_correct": n,
        "work_clock_tier": tier,
        "invalid_reason": reason,
    }


def test_index_100_when_equal():
    ref = _clock(sec=2.0)
    assert compute_speed_index(ref, _clock(sec=2.0)) == 100


def test_index_200_when_twice_as_fast():
    ref = _clock(sec=4.0)
    assert compute_speed_index(ref, _clock(sec=2.0)) == 200


def test_index_null_tier_mismatch():
    ref = _clock(sec=2.0, tier="standard")
    assert compute_speed_index(ref, _clock(sec=2.0, tier="smoke")) is None


def test_index_null_contaminated():
    ref = _clock(sec=2.0)
    dirty = _clock(sec=2.0, reason="sticky min_tokens")
    assert compute_speed_index(ref, dirty) is None
    assert compute_speed_index(dirty, ref) is None


def test_index_null_n_correct_drift():
    ref = _clock(sec=2.0, n=400)
    assert compute_speed_index(ref, _clock(sec=2.0, n=449)) == 100
    assert compute_speed_index(ref, _clock(sec=2.0, n=451)) is None


def test_index_null_without_reference():
    assert compute_speed_index(None, _clock(sec=2.0)) is None
    clocks = {"a": _clock(sec=2.0)}
    attach_speed_indexes(clocks, None)
    assert clocks["a"]["work_clock_index"] is None
    assert clocks["a"]["work_clock_reference"] is None


def test_attach_stamps_reference_fields():
    clocks = {
        "holo": _clock(sec=1.76, n=442),
        "glm": _clock(sec=33.07, n=433),
    }
    attach_speed_indexes(clocks, "holo")
    assert clocks["holo"]["work_clock_index"] == 100
    assert clocks["glm"]["work_clock_index"] == 5
    assert clocks["glm"]["work_clock_reference"] == "holo"
    assert clocks["glm"]["work_clock_reference_sec"] == 1.76
