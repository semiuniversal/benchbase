"""Ranking cohort and compatibility classification (vNext WP1)."""

from __future__ import annotations

from typing import Any

STANDARD_COHORT_TIERS = frozenset({"standard", "thorough"})

COMPATIBILITY_EXACTLY = "exactly_compatible"
COMPATIBILITY_LEGACY = "legacy_non_equivalent"
COMPATIBILITY_INSUFFICIENT = "insufficient_evidence"


def cohort_eligible(best_tier: str | None, ranking_cohort: str) -> bool:
    if ranking_cohort == "all_eligible":
        return True
    if ranking_cohort == "standard_completed":
        return best_tier in STANDARD_COHORT_TIERS
    return True


def compatibility_class(
    *,
    invalid: bool,
    mismatched: bool,
    incomplete: bool,
    primary: float | None,
) -> str:
    if invalid or mismatched:
        return COMPATIBILITY_LEGACY
    if incomplete or primary is None:
        return COMPATIBILITY_INSUFFICIENT
    return COMPATIBILITY_EXACTLY


def attach_cohort_metadata(
    scorecards: list[dict[str, Any]],
    *,
    ranking_cohort: str,
) -> None:
    for sc in scorecards:
        tier = sc.get("best_tier")
        eligible = cohort_eligible(tier, ranking_cohort)
        sc["ranking_cohort"] = ranking_cohort
        sc["cohort_eligible"] = eligible