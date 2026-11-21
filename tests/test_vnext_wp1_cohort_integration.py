"""WP1: standard vs smoke Borda pools with two models."""

from __future__ import annotations

from benchbase.scoring import _build_scorecards


def _mk_model(name: str, tier: str, score: float) -> dict:
    from benchbase.db.models import Result

    r = Result(
        task_name="knowledge:v2",
        score=score,
        n_items=100,
        metrics_json='{"successes": 90, "planned_n": 100}',
    )
    return {
        "model_name": name,
        "best_tier": tier,
        "suite_versions": {"knowledge": "v2"},
        "axis_runs": {"knowledge": [r]},
        "all_results": [r],
        "has_benchmark_history": True,
        "is_active": True,
        "status": "active",
    }


def test_smoke_does_not_affect_standard_overall_rank():
    versions = {a: "v2" for a in (
        "knowledge", "reasoning", "math", "coding", "tool_calling",
        "instruction", "structured", "long_context",
    )}
    status = {a: "valid" for a in versions}
    models = {
        "smoke-star": _mk_model("smoke-star", "smoke", 99.0),
        "std-ok": _mk_model("std-ok", "standard", 80.0),
    }
    std_cards = _build_scorecards(
        models, versions, status, work_clocks={}, ranking_cohort="standard_completed"
    )
    by_name = {c["model_name"]: c for c in std_cards}
    assert by_name["smoke-star"]["cohort_eligible"] is False
    assert by_name["std-ok"]["cohort_eligible"] is True
    assert by_name["std-ok"]["overall_rank"] == 1

    all_cards = _build_scorecards(
        models, versions, status, work_clocks={}, ranking_cohort="all_eligible"
    )
    by_all = {c["model_name"]: c for c in all_cards}
    assert by_all["smoke-star"]["cohort_eligible"] is True
    # smoke-star has higher knowledge score → should win overall in legacy pool
    assert by_all["smoke-star"]["overall_rank"] == 1


def test_compatibility_class_on_dimension():
    cards = _build_scorecards(
        {
            "m": {
                "model_name": "m",
                "best_tier": "standard",
                "suite_versions": {"knowledge": "v1"},
                "axis_runs": {},
                "all_results": [],
            }
        },
        {"knowledge": "v2"},
        {"knowledge": "valid"},
        work_clocks={},
    )
    assert cards[0]["dimensions"]["knowledge"]["compatibility_class"] == "legacy_non_equivalent"