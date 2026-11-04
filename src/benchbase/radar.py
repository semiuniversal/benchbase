"""Radar chart payload shaped from model-scorecard rows (Compare page)."""

from __future__ import annotations

from typing import Any

from benchbase.scoring import RADAR_AXES

AXIS_LABELS: dict[str, str] = {
    "knowledge": "Knowledge",
    "reasoning": "Reasoning",
    "math": "Math",
    "coding": "Coding",
    "tool_calling": "Tool calling",
    "instruction": "Instruction",
    "structured": "Structured",
    "long_context": "Long context",
}


def _as_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if isinstance(e, dict) and e.get("model_name")]


def filter_radar_entries(
    entries: list[dict[str, Any]],
    *,
    model_names: list[str] | None = None,
    active_only: bool = False,
    show_smoke: bool = False,
    show_unbenchmarked: bool = False,
    group_by_family: bool = False,
) -> list[dict[str, Any]]:
    """Apply Compare-page display filters (archived models never plot)."""
    catalog = [e for e in _as_entries(entries) if e.get("status") != "archived"]
    if model_names:
        wanted = set(model_names)
        catalog = [e for e in catalog if e.get("model_name") in wanted]
    if active_only:
        catalog = [e for e in catalog if e.get("is_active") is True or e.get("status") == "active"]
    if not show_unbenchmarked:
        catalog = [e for e in catalog if e.get("has_benchmark_history")]
    if not show_smoke:
        catalog = [e for e in catalog if e.get("best_tier") != "smoke"]
    if group_by_family:
        by_base: dict[str, dict[str, Any]] = {}
        for entry in catalog:
            key = str(entry.get("base_model") or entry.get("model_name"))
            prev = by_base.get(key)
            if not prev or (entry.get("quant_rank") or 0) > (prev.get("quant_rank") or 0):
                by_base[key] = entry
        catalog = list(by_base.values())
    return catalog


def _stretch_bounds(models: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float]]:
    mins: dict[str, float] = {}
    maxs: dict[str, float] = {}
    for axis in RADAR_AXES:
        vals = [
            e.get("dimensions", {}).get(axis, {}).get("primary")
            for e in models
        ]
        nums = [v for v in vals if isinstance(v, (int, float))]
        mins[axis] = min(nums) if nums else 0.0
        maxs[axis] = max(nums) if nums else 100.0
        if mins[axis] == maxs[axis]:
            mins[axis] = max(0.0, mins[axis] - 1.0)
            maxs[axis] = min(100.0, maxs[axis] + 1.0)
    return mins, maxs


def _scaled(raw: float, axis: str, mins: dict[str, float], maxs: dict[str, float]) -> float:
    span = maxs[axis] - mins[axis] or 1.0
    return ((raw - mins[axis]) / span) * 100.0


def shape_radar_chart_data(
    entries: list[dict[str, Any]],
    *,
    model_names: list[str] | None = None,
    stretch: bool = False,
    group_by_family: bool = False,
    active_only: bool = False,
    show_smoke: bool = False,
    show_unbenchmarked: bool = False,
) -> dict[str, Any]:
    """Return plot-ready radar JSON: six quality axes, per-model scores, Wilson CI."""
    models = filter_radar_entries(
        entries,
        model_names=model_names,
        active_only=active_only,
        show_smoke=show_smoke,
        show_unbenchmarked=show_unbenchmarked,
        group_by_family=group_by_family,
    )
    mins: dict[str, float] = {}
    maxs: dict[str, float] = {}
    if stretch:
        mins, maxs = _stretch_bounds(models)

    axes: list[dict[str, Any]] = []
    radar_data: list[dict[str, Any]] = []
    for axis in RADAR_AXES:
        label = AXIS_LABELS[axis]
        if stretch:
            label = f"{label} ({mins[axis]:.0f}–{maxs[axis]:.0f})"
        scores: dict[str, Any] = {}
        row: dict[str, Any] = {"axis": label, "_axisKey": axis}
        for entry in models:
            name = entry["model_name"]
            dim = (entry.get("dimensions") or {}).get(axis) or {}
            raw = dim.get("primary")
            if raw is None:
                value = None
            elif stretch:
                value = _scaled(float(raw), axis, mins, maxs)
            else:
                value = raw
            scores[name] = {
                "value": value,
                "raw": raw,
                "ci_low": dim.get("ci_low"),
                "ci_high": dim.get("ci_high"),
                "n_items": dim.get("n_items"),
                "planned_n": dim.get("planned_n"),
                "rank": dim.get("rank"),
                "unit": dim.get("unit", "%"),
            }
            row[name] = value
        axes.append({"key": axis, "label": label, "scores": scores})
        radar_data.append(row)

    series = [
        {
            "model_name": e["model_name"],
            "model_color": e.get("model_color"),
            "overall_rank": e.get("overall_rank"),
            "overall_rank_tied": e.get("overall_rank_tied"),
            "borda_score": e.get("borda_score"),
            "best_tier": e.get("best_tier"),
        }
        for e in models
    ]
    return {
        "axes": axes,
        "series": series,
        "radar_data": radar_data,
        "stretch": stretch,
        "axis_keys": list(RADAR_AXES),
    }
