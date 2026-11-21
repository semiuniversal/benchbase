"""Server-side scorecard CSV (matches frontend exportScorecardCsv.ts)."""

from __future__ import annotations

import csv
import io
from typing import Any

EXPORT_QUALITY_AXES = (
    "knowledge",
    "reasoning",
    "math",
    "coding",
    "tool_calling",
    "instruction",
    "structured",
    "long_context",
)
GATE_AXES = frozenset({"structured", "long_context"})


def _axis_headers(axis: str) -> list[str]:
    cols = [
        f"{axis}_score",
        f"{axis}_ci_low",
        f"{axis}_ci_high",
        f"{axis}_rank",
        f"{axis}_borda_points",
        f"{axis}_n_items",
        f"{axis}_planned_n",
    ]
    if axis in GATE_AXES:
        cols.append(f"{axis}_pass")
    return cols


def _gate_pass_cell(d: dict[str, Any] | None) -> str:
    if not d or d.get("primary") is None:
        return ""
    if d.get("gate_pass") is not None:
        return "true" if d["gate_pass"] else "false"
    return "true" if float(d["primary"]) >= 100 else "false"


def scorecard_to_csv(
    scorecard: list[dict[str, Any]],
    models_by_name: dict[str, dict[str, Any]] | None = None,
) -> str:
    models_by_name = models_by_name or {}
    headers = [
        "model_name",
        "status",
        "is_active",
        "base_model",
        "best_tier",
        "ranking_cohort",
        "cohort_eligible",
        "context_window",
        "vram_gb",
        "notes",
        "overall_rank",
        "overall_rank_tied",
        "overall_competitors",
        "borda_score",
        *[_h for axis in EXPORT_QUALITY_AXES for _h in _axis_headers(axis)],
        "speed_index",
        "speed_index_reference",
        "sec_per_correct",
        "suite_wall_s",
        "n_correct",
        "work_clock_tier",
        "output_tps",
        "prefill_tps",
        "ttft_ms",
        "think_ms",
        "think_tokens",
        "speed_invalid_reason",
    ]
    rows = sorted(
        scorecard,
        key=lambda e: (
            e.get("overall_rank") if e.get("overall_rank") is not None else 9999,
            e.get("model_name") or "",
        ),
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for e in rows:
        model = models_by_name.get(e.get("model_name", ""), {})
        sp = e.get("speed") or {}
        cells: list[Any] = [
            e.get("model_name"),
            e.get("status") or model.get("status") or "",
            e.get("is_active") if e.get("is_active") is not None else model.get("is_active", ""),
            e.get("base_model") or model.get("base_model") or "",
            e.get("best_tier") or "",
            e.get("ranking_cohort") or "standard_completed",
            e.get("cohort_eligible", ""),
            e.get("context_window") if e.get("context_window") is not None else model.get("context_window", ""),
            e.get("vram_gb") if e.get("vram_gb") is not None else model.get("vram_gb", ""),
            model.get("notes") or "",
            e.get("overall_rank"),
            e.get("overall_rank_tied", False),
            e.get("overall_competitors"),
            e.get("borda_score"),
        ]
        dims = e.get("dimensions") or {}
        for axis in EXPORT_QUALITY_AXES:
            d = dims.get(axis) or {}
            cells.extend(
                [
                    d.get("primary"),
                    d.get("ci_low"),
                    d.get("ci_high"),
                    d.get("rank"),
                    d.get("borda_points"),
                    d.get("n_items"),
                    d.get("planned_n"),
                ]
            )
            if axis in GATE_AXES:
                cells.append(_gate_pass_cell(d))
        cells.extend(
            [
                sp.get("work_clock_index"),
                sp.get("work_clock_reference"),
                sp.get("sec_per_correct"),
                sp.get("suite_wall_s"),
                sp.get("n_correct"),
                sp.get("work_clock_tier"),
                sp.get("output_tps"),
                sp.get("prefill_tps"),
                sp.get("ttft_ms"),
                sp.get("think_ms"),
                sp.get("think_tokens"),
                sp.get("invalid_reason"),
            ]
        )
        writer.writerow(cells)
    return buf.getvalue()