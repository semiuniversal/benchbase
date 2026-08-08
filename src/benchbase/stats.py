"""Wilson confidence intervals and paired comparison stats."""

from __future__ import annotations

import math
from typing import Iterable


def wilson_interval(
    successes: int, n: int, z: float = 1.96
) -> tuple[float | None, float | None]:
    """Wilson score 95% CI on a proportion, returned as 0–100 score bounds."""
    if n <= 0:
        return None, None
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)) / denom
    low = max(0.0, (center - margin) * 100.0)
    high = min(100.0, (center + margin) * 100.0)
    return low, high


def proportion_score(successes: int, n: int) -> float | None:
    if n <= 0:
        return None
    return round(100.0 * successes / n, 1)


def mcnemar_verdict(
    a_pass_b_fail: int,
    a_fail_b_pass: int,
    alpha: float = 0.05,
) -> str:
    """
    Continuity-corrected McNemar on discordant pairs.

    Returns one of: 'A > B (p<0.05)', 'B > A (p<0.05)',
    'no detectable difference', 'insufficient data'.
    """
    n = a_pass_b_fail + a_fail_b_pass
    if n < 5:
        return "insufficient data"
    # Chi-square with continuity correction
    chi2 = (abs(a_pass_b_fail - a_fail_b_pass) - 1) ** 2 / n
    # Critical value for alpha=0.05, df=1
    if chi2 < 3.841:
        return "no detectable difference"
    if a_pass_b_fail > a_fail_b_pass:
        return "A > B (p<0.05)"
    return "B > A (p<0.05)"


def mcnemar_from_items(
    a_passed: dict[str, bool],
    b_passed: dict[str, bool],
) -> str:
    shared = set(a_passed) & set(b_passed)
    if not shared:
        return "insufficient data"
    ap_bf = sum(1 for i in shared if a_passed[i] and not b_passed[i])
    af_bp = sum(1 for i in shared if not a_passed[i] and b_passed[i])
    return mcnemar_verdict(ap_bf, af_bp)


def borda_points(ranks: Iterable[int | None], n_competitors: int) -> int:
    """Sum of (n - rank + 1) for ranked axes; unranked contribute 0."""
    total = 0
    for r in ranks:
        if r is None:
            continue
        total += max(0, n_competitors - r + 1)
    return total
