"""Work clock: wall sum, n_correct, sitting pick, contaminated sittings."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from benchbase.db.models import RunStatus
from benchbase.scoring import _extract_speed
from benchbase.work_clock import (
    CONTAMINATED_GROUP_IDS,
    CONTAMINATED_REASON,
    WORK_CLOCK_AXES,
    AxisWall,
    Sitting,
    n_correct,
    pick_sitting,
    quality_complete,
    sittings_from_runs,
    successes_from_metrics,
    suite_wall_s,
    work_clock_payload,
)


def _start() -> datetime:
    return datetime(2026, 8, 1, 12, 0, 0)


def _wall(
    axis: str,
    run_id: int,
    successes: int,
    wall_s: float,
    status: str = RunStatus.COMPLETED.value,
) -> AxisWall:
    start = _start()
    return AxisWall(
        axis=axis,
        run_id=run_id,
        status=status,
        started_at=start,
        completed_at=start + timedelta(seconds=wall_s),
        successes=successes,
    )


def _sitting(
    group: str,
    tier: str,
    *,
    run_id0: int = 1,
    successes: int = 10,
    wall_s: float = 20.0,
    skip_axis: str | None = None,
    failed_axis: str | None = None,
) -> Sitting:
    sitting = Sitting(
        run_group_id=group,
        model_id=1,
        model_name="seat",
        tier=tier,
    )
    for i, axis in enumerate(WORK_CLOCK_AXES):
        if axis == skip_axis:
            continue
        status = (
            RunStatus.FAILED.value
            if axis == failed_axis
            else RunStatus.COMPLETED.value
        )
        sitting.axes[axis] = _wall(
            axis, run_id0 + i, successes, wall_s, status=status
        )
    return sitting


def test_successes_from_metrics_json():
    assert successes_from_metrics('{"successes": 42}') == 42
    assert successes_from_metrics(None) == 0
    assert successes_from_metrics("{") == 0
    assert successes_from_metrics('{"successes": true}') == 0


def test_wall_sum_and_n_correct():
    sitting = _sitting("g1", "standard", successes=5, wall_s=10.0)
    assert quality_complete(sitting)
    assert suite_wall_s(sitting) == 80.0
    assert n_correct(sitting) == 40
    payload = work_clock_payload(sitting)
    assert payload["sec_per_correct"] == 2.0
    assert payload["suite_wall_s"] == 80.0
    assert payload["n_correct"] == 40
    assert payload["work_clock_tier"] == "standard"
    assert payload["invalid_reason"] is None


def test_prefer_standard_over_smoke():
    smoke = _sitting("smoke-old", "smoke", run_id0=100, successes=8, wall_s=5.0)
    standard = _sitting("std-new", "standard", run_id0=10, successes=4, wall_s=20.0)
    chosen = pick_sitting([smoke, standard])
    assert chosen is not None
    assert chosen.run_group_id == "std-new"


def test_smoke_when_no_standard():
    smoke = _sitting("smoke-only", "smoke", run_id0=1)
    chosen = pick_sitting([smoke])
    assert chosen is not None
    assert chosen.run_group_id == "smoke-only"
    assert work_clock_payload(chosen)["work_clock_tier"] == "smoke"


def test_latest_standard_wins():
    older = _sitting("std-a", "standard", run_id0=1)
    newer = _sitting("std-b", "standard", run_id0=80)
    chosen = pick_sitting([older, newer])
    assert chosen is not None
    assert chosen.run_group_id == "std-b"


def test_incomplete_quality_not_picked():
    incomplete = _sitting("std-gap", "standard", skip_axis="long_context")
    smoke = _sitting("smoke-ok", "smoke", run_id0=50)
    assert not quality_complete(incomplete)
    chosen = pick_sitting([incomplete, smoke])
    assert chosen is not None
    assert chosen.run_group_id == "smoke-ok"


def test_contaminated_nulls_sec_per_correct():
    gid = next(iter(CONTAMINATED_GROUP_IDS))
    sitting = _sitting(gid, "standard", successes=10, wall_s=100.0)
    payload = work_clock_payload(sitting)
    assert payload["sec_per_correct"] is None
    assert payload["invalid_reason"] == CONTAMINATED_REASON
    assert payload["n_correct"] == 80
    assert payload["suite_wall_s"] == 800.0


def test_zero_correct_is_null():
    sitting = _sitting("g", "standard", successes=0, wall_s=10.0)
    payload = work_clock_payload(sitting)
    assert payload["sec_per_correct"] is None
    assert payload["n_correct"] == 0


def test_speed_failed_sibling_still_counts():
    """sittings_from_runs ignores Speed; eight completed quality axes are enough."""
    start = _start()
    model = SimpleNamespace(name="seat")
    suite = lambda axis: SimpleNamespace(axis=SimpleNamespace(value=axis))
    runs = []
    for i, axis in enumerate(WORK_CLOCK_AXES):
        runs.append(
            SimpleNamespace(
                id=i + 1,
                run_group_id="tier-abc",
                model_id=1,
                model=model,
                tier=SimpleNamespace(value="standard"),
                status=RunStatus.COMPLETED,
                started_at=start,
                completed_at=start + timedelta(seconds=8),
                suite=suite(axis),
                results=[
                    SimpleNamespace(metrics_json='{"successes": 3}'),
                ],
            )
        )
    runs.append(
        SimpleNamespace(
            id=99,
            run_group_id="tier-abc",
            model_id=1,
            model=model,
            tier=SimpleNamespace(value="standard"),
            status=RunStatus.FAILED,
            started_at=start,
            completed_at=None,
            suite=suite("speed") if False else SimpleNamespace(axis=SimpleNamespace(value="speed")),
            results=[],
        )
    )
    sittings = sittings_from_runs(runs)  # type: ignore[arg-type]
    assert len(sittings) == 1
    assert quality_complete(sittings[0])
    payload = work_clock_payload(sittings[0])
    assert payload["n_correct"] == 24
    assert payload["sec_per_correct"] == 2.67


def test_extract_speed_payload_includes_work_clock_fields():
    clock = {
        "sec_per_correct": 4.5,
        "suite_wall_s": 90.0,
        "n_correct": 20,
        "work_clock_tier": "standard",
        "invalid_reason": None,
        "work_clock_group": "tier-x",
    }
    speed = _extract_speed([], work_clock=clock)
    assert speed["output_tps"] is None
    assert speed["sec_per_correct"] == 4.5
    assert speed["suite_wall_s"] == 90.0
    assert speed["n_correct"] == 20
    assert speed["work_clock_tier"] == "standard"
    assert speed["work_clock_group"] == "tier-x"
    empty = _extract_speed([])
    assert empty["sec_per_correct"] is None
    assert empty["output_tps"] is None
    assert empty["work_clock_index"] is None
