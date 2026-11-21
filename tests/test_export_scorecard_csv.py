from benchbase.export_scorecard_csv import scorecard_to_csv


def test_csv_header_includes_cohort_columns():
    csv = scorecard_to_csv(
        [
            {
                "model_name": "smoke-only",
                "best_tier": "smoke",
                "ranking_cohort": "standard_completed",
                "cohort_eligible": False,
                "borda_score": 0,
                "overall_rank": None,
                "dimensions": {},
                "speed": {},
            }
        ]
    )
    header = csv.splitlines()[0]
    assert "ranking_cohort" in header
    assert "cohort_eligible" in header
    assert "cohort_eligible" in csv
    assert ",False," in csv or ",false," in csv.lower() or "False" in csv