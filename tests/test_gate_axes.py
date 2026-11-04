"""Structured and long context stay scored and do not move Borda."""

from benchbase.db.models import Result
from benchbase.scoring import GATE_AXES, RADAR_AXES, _build_scorecards, gate_pass


def _axis_result(axis: str, score: float) -> Result:
    return Result(
        task_name=f"{axis}:primary",
        score=score,
        n_items=10,
        metrics_json='{"planned_n": 10}',
    )


def test_gate_pass_is_a_perfect_score():
    assert gate_pass(None) is None
    assert gate_pass(100) is True
    assert gate_pass(99.9) is False


def test_gates_are_exported_on_the_card_and_excluded_from_borda():
    versions = {axis: "v3" for axis in RADAR_AXES + GATE_AXES}

    def pack(name: str, radar_score: float, structured: float, long_context: float) -> dict:
        axis_runs = {axis: [_axis_result(axis, radar_score)] for axis in RADAR_AXES}
        axis_runs["structured"] = [_axis_result("structured", structured)]
        axis_runs["long_context"] = [_axis_result("long_context", long_context)]
        return {
            "model_name": name,
            "host": "mastiff",
            "base_model": "glm",
            "suite_versions": dict(versions),
            "axis_runs": axis_runs,
            "all_results": [],
        }

    cards = _build_scorecards(
        {
            "strong": pack("strong", 80, 100, 100),
            "weak": pack("weak", 40, 50, 0),
        },
        versions,
        {},
    )
    by_name = {card["model_name"]: card for card in cards}
    strong = by_name["strong"]
    weak = by_name["weak"]

    assert strong["host"] == "mastiff"
    assert strong["dimensions"]["structured"]["primary"] == 100
    assert strong["dimensions"]["structured"]["gate_pass"] is True
    assert weak["dimensions"]["long_context"]["gate_pass"] is False
    assert strong["dimensions"]["structured"]["borda_points"] == 0
    assert weak["dimensions"]["long_context"]["borda_points"] == 0
    # Six radar axes, rank 1 of 2 → 1 point each. Gates add nothing.
    assert strong["borda_score"] == len(RADAR_AXES)
    assert weak["borda_score"] == 0
    assert strong["overall_rank"] == 1
