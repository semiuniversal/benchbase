"""Speed runner tier profile: replicate count and pp list."""

from __future__ import annotations

import json

from benchbase.db.models import BenchmarkAxis, BenchmarkSuite, Run, RunTier
from benchbase.runners.speed import _speed_pp_list, _speed_runs_count

SPEED_CFG = {
    "profile_id": "decode-4k-512-c1-v1",
    "pp": [4096, 32768],
    "passes": {"smoke": 3, "standard": 5, "thorough": 5},
}


def _run(tier: RunTier) -> Run:
    suite = BenchmarkSuite(
        name="Speed",
        axis=BenchmarkAxis.SPEED,
        category=BenchmarkAxis.SPEED,
        runner_class="speed",
        config_json=json.dumps(SPEED_CFG),
    )
    return Run(
        model_id=1,
        suite_id=1,
        tier=tier,
        metadata_json=json.dumps({"runs": 3, "batch": True}),
        suite=suite,
    )


def test_speed_runs_count_ignores_stale_batch_metadata_for_decode_profile():
    run = _run(RunTier.STANDARD)
    assert _speed_runs_count(run, SPEED_CFG) == 5


def test_speed_pp_list_standard_is_4k_only():
    run = _run(RunTier.STANDARD)
    assert _speed_pp_list(run, SPEED_CFG) == [4096]


def test_speed_pp_list_thorough_includes_32k():
    run = _run(RunTier.THOROUGH)
    assert _speed_pp_list(run, SPEED_CFG) == [4096, 32768]