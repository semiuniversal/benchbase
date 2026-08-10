"""Unit tests for T_eff metrics."""

from __future__ import annotations

import math

from benchbase.agentic.ledger import AttemptLedger
from benchbase.agentic.metrics import compute_task_metrics, geometric_mean_teff_ratio


def test_teff_basic():
    ledgers = [
        AttemptLedger(wall_seconds=10, resolved=True, tokens_prompt=100, tokens_completion=50),
        AttemptLedger(wall_seconds=20, resolved=False, tokens_prompt=100, tokens_completion=50),
    ]
    m = compute_task_metrics("t1", ledgers)
    assert m.p_success == 0.5
    assert m.mean_wall_seconds == 15
    assert m.t_eff == 30.0
    assert m.reliability_inv == 2.0


def test_teff_p0_infinite_excluded():
    ledgers = [AttemptLedger(wall_seconds=5, resolved=False)]
    m = compute_task_metrics("t2", ledgers)
    assert m.t_eff_infinite
    assert m.excluded_from_geomean
    assert m.t_eff is math.inf or m.t_eff_infinite


def test_geomean_self_is_one():
    a = compute_task_metrics(
        "a",
        [AttemptLedger(wall_seconds=10, resolved=True, tokens_prompt=10, tokens_completion=10)],
    )
    b = compute_task_metrics(
        "b",
        [
            AttemptLedger(wall_seconds=20, resolved=True, tokens_prompt=10, tokens_completion=10),
            AttemptLedger(wall_seconds=20, resolved=False, tokens_prompt=10, tokens_completion=10),
        ],
    )
    geo = geometric_mean_teff_ratio([a, b], [a, b])
    assert geo["geo_mean"] is not None
    assert abs(geo["geo_mean"] - 1.0) < 1e-9


def test_unsolvable_excluded():
    m = compute_task_metrics(
        "probe",
        [AttemptLedger(wall_seconds=3, resolved=False, abstained=True)],
        expected="unsolvable",
    )
    assert m.excluded_from_geomean
    assert m.false_confidence is not None
