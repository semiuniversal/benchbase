"""Dashboard headline selection (D1 acceptance subset)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from benchbase.dashboard_headlines import (
    build_run_groups,
    headline_from_group,
    rollup_status,
    select_headlines,
    tier_label,
)
from benchbase.db.models import RunStatus, RunTier


def _run(
    *,
    run_id: int,
    status: RunStatus,
    group: str | None = "tier-abc",
    tier: RunTier = RunTier.STANDARD,
    completed_at: datetime | None = None,
    suite_name: str = "Knowledge",
):
    return SimpleNamespace(
        id=run_id,
        run_group_id=group,
        status=status,
        tier=tier,
        started_at=datetime(2026, 1, 1, 12, 0, 0),
        completed_at=completed_at,
        metadata_json=None,
        model=SimpleNamespace(id=1, name="Test Model"),
        suite=SimpleNamespace(name=suite_name, runner_class="knowledge"),
    )


def test_rollup_running_wins_over_completed_sibling():
    members = [
        _run(run_id=1, status=RunStatus.COMPLETED, completed_at=datetime(2026, 1, 1, 13)),
        _run(run_id=2, status=RunStatus.RUNNING, suite_name="Speed"),
    ]
    assert rollup_status(members) == RunStatus.RUNNING.value


def test_one_completion_headline_per_group():
    now = datetime(2026, 6, 1, 12, 0, 0)
    members = [
        _run(
            run_id=i,
            status=RunStatus.COMPLETED,
            completed_at=now - timedelta(hours=i),
            suite_name=f"Axis{i}",
        )
        for i in range(8)
    ]
    groups = build_run_groups(members)
    assert len(groups) == 1
    headlines = select_headlines(groups, now=now)
    completed = [h for h in headlines if h["type"] == "benchmark.completed"]
    assert len(completed) == 1


def test_smoke_labeled_not_standard():
    assert tier_label("smoke") == "Smoke"
    members = [
        _run(
            run_id=1,
            status=RunStatus.COMPLETED,
            tier=RunTier.SMOKE,
            completed_at=datetime(2026, 6, 1),
        ),
    ]
    groups = build_run_groups(members)
    h = headline_from_group(groups[0], now=datetime(2026, 6, 2))
    assert h is not None
    assert "Smoke" in h["title"]


def test_failed_not_completed():
    now = datetime(2026, 6, 1)
    members = [_run(run_id=1, status=RunStatus.FAILED)]
    groups = build_run_groups(members)
    h = headline_from_group(groups[0], now=now)
    assert h is not None
    assert h["type"] == "benchmark.interrupted"


def test_empty_groups_yield_no_headlines():
    assert select_headlines([], now=datetime(2026, 6, 1)) == []


def test_destination_uses_group_query():
    members = [_run(run_id=1, status=RunStatus.RUNNING)]
    groups = build_run_groups(members)
    dest = headline_from_group(groups[0], now=datetime(2026, 6, 1))["destination"]
    assert dest["routeName"] == "benchmarks"
    assert dest["query"]["group"] == "tier-abc"
    assert dest["query"]["open"] == "1"


def test_running_queued_interrupted_priority_order():
    now = datetime(2026, 6, 1, 12, 0, 0)
    groups = build_run_groups(
        [
            _run(
                run_id=1,
                group="g-done",
                status=RunStatus.COMPLETED,
                completed_at=now - timedelta(hours=1),
            ),
            _run(run_id=2, group="g-run", status=RunStatus.RUNNING),
            _run(run_id=3, group="g-fail", status=RunStatus.FAILED),
            _run(run_id=4, group="g-wait", status=RunStatus.PENDING),
        ]
    )
    headlines = select_headlines(groups, now=now)
    types = [h["type"] for h in headlines]
    assert types.index("benchmark.running") < types.index("benchmark.interrupted")
    assert "benchmark.queued" in types