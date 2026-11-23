"""Speed runner tier profile: replicate count and pp list."""

from __future__ import annotations

import json

from benchbase.db.models import BenchmarkAxis, BenchmarkSuite, Run, RunTier
from benchbase.decode_tps import PROFILE_ID_NATURAL
from benchbase.decode_tps import suite_forcing
from benchbase.runners.speed import _speed_pp_list, _speed_runs_count

SPEED_CFG = {
    "profile_id": PROFILE_ID_NATURAL,
    "forcing": "natural",
    "pp": [4096],
    "passes": {"smoke": 3, "standard": 5, "thorough": 5},
}

SPEED_EXACT_CFG = {
    "profile_id": "decode-4k-512-exact-c1-v1",
    "forcing": "exact",
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


def test_speed_pp_list_thorough_natural_4k_only():
    run = _run(RunTier.THOROUGH)
    assert _speed_pp_list(run, SPEED_CFG) == [4096]


def test_speed_pp_list_thorough_exact_includes_32k_when_configured():
    run = _run(RunTier.THOROUGH)
    run.suite.config_json = json.dumps(SPEED_EXACT_CFG)
    assert _speed_pp_list(run, SPEED_EXACT_CFG) == [4096, 32768]


def test_suite_forcing_natural_by_default():
    assert suite_forcing(SPEED_CFG, PROFILE_ID_NATURAL) == "natural"
    assert suite_forcing(SPEED_EXACT_CFG, SPEED_EXACT_CFG["profile_id"]) == "exact"