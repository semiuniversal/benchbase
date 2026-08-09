"""Negative controls (null / random / echo) and scorer-invalid gate."""

from __future__ import annotations

import json
import logging
import random
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import (
    BenchmarkAxis,
    BenchmarkSuite,
    Model,
    ModelStatus,
    Result,
    Run,
    RunStatus,
    RunTier,
    SettingEntry,
)
from benchbase.runners.quality_common import CONTROL_MODEL_NAMES, load_fixture_items
from benchbase.stats import wilson_interval

logger = logging.getLogger(__name__)

CONTROL_DEFS = [
    {"name": "__control_null__", "label": "null"},
    {"name": "__control_random__", "label": "random"},
    {"name": "__control_echo__", "label": "echo"},
]

# Axes that run through quality runners (speed is not controlled the same way).
CONTROL_AXES = [
    BenchmarkAxis.SMOKE,
    BenchmarkAxis.KNOWLEDGE,
    BenchmarkAxis.REASONING,
    BenchmarkAxis.MATH,
    BenchmarkAxis.CODING,
    BenchmarkAxis.TOOL_CALLING,
    BenchmarkAxis.INSTRUCTION,
    BenchmarkAxis.STRUCTURED,
    BenchmarkAxis.LONG_CONTEXT,
]

_MC_AXES = {BenchmarkAxis.KNOWLEDGE, BenchmarkAxis.REASONING, BenchmarkAxis.SMOKE}
_GENERATIVE_AXES = {
    BenchmarkAxis.MATH,
    BenchmarkAxis.CODING,
    BenchmarkAxis.INSTRUCTION,
    BenchmarkAxis.STRUCTURED,
    BenchmarkAxis.LONG_CONTEXT,
}


def is_control_model_name(name: str) -> bool:
    return name in CONTROL_MODEL_NAMES


def control_respond(
    model: str,
    messages: list[dict[str, str]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """Synthetic model responses for negative controls."""
    prompt = ""
    for m in messages:
        prompt += m.get("content") or ""
    if model == "__control_null__":
        return ""
    if model == "__control_echo__":
        return prompt
    if model == "__control_random__":
        # MC: uniform random letter when the prompt is clearly multiple-choice.
        if re.search(r"Answer with A,\s*B,\s*C,\s*or D only", prompt, re.I):
            return random.choice(["A", "B", "C", "D"])
        if tools:
            names = []
            for t in tools:
                if isinstance(t, dict):
                    n = t.get("name") or (t.get("function") or {}).get("name")
                    if n:
                        names.append(n)
            if names:
                return json.dumps({"name": random.choice(names), "arguments": {}})
        # Fixed nonsense for generative prompts. Prefer failing common IFEval rules.
        return "FORBIDDEN_WORD_xyzzy, and also THIS_IS_WRONG"
    return ""


def _scorer_key(axis: str, suite_version: str) -> str:
    return f"scorer_status:{axis}:{suite_version}"


async def ensure_control_models(db: AsyncSession) -> list[Model]:
    """Create archived control model rows if missing."""
    models = []
    for cdef in CONTROL_DEFS:
        result = await db.execute(select(Model).where(Model.name == cdef["name"]))
        model = result.scalar_one_or_none()
        if not model:
            model = Model(
                name=cdef["name"],
                endpoint_url="control://local",
                status=ModelStatus.ARCHIVED,
                is_active=False,
                color="gray",
                base_model="control",
                quantization=cdef["label"],
            )
            db.add(model)
            await db.flush()
        else:
            model.set_status(ModelStatus.ARCHIVED)
        models.append(model)
    await db.flush()
    return models


def _bound_ok(control_label: str, axis: BenchmarkAxis, score: float | None, n: int) -> bool:
    if score is None:
        return False
    if control_label == "null":
        return score == 0
    if control_label == "echo":
        return score == 0
    if control_label == "random":
        if axis in _MC_AXES or axis == BenchmarkAxis.SMOKE:
            # Chance ± Wilson on 4-choice; allow score within chance CI upper + small slack.
            # For smoke mixed checks, treat like generative: ≤ 25 is soft; use ≤ 40.
            if axis == BenchmarkAxis.SMOKE:
                return score <= 40
            lo, hi = wilson_interval(int(round(0.25 * n)), n) if n else (0.0, 100.0)
            # score is 0-100; wilson_interval returns 0-100 already in this codebase?
            return score <= max(hi or 40, 40)
        if axis == BenchmarkAxis.TOOL_CALLING:
            # Irrelevance base: random tool call fails irrelevance; expect low overall.
            return score <= 30
        if axis in _GENERATIVE_AXES:
            return score <= 5
        return score <= 5
    return False


async def evaluate_control_bounds(db: AsyncSession) -> dict[str, Any]:
    """Read latest control runs for current suite versions; update scorer_status keys."""
    suites = (await db.execute(select(BenchmarkSuite))).scalars().all()
    by_axis = {s.axis: s for s in suites}
    report: dict[str, Any] = {"suites": {}, "all_valid": True}

    for axis in CONTROL_AXES:
        suite = by_axis.get(axis)
        if not suite:
            continue
        axis_key = axis.value
        version = suite.suite_version
        axis_report: dict[str, Any] = {"suite_version": version, "controls": {}, "valid": True}

        for cdef in CONTROL_DEFS:
            model = (
                await db.execute(select(Model).where(Model.name == cdef["name"]))
            ).scalar_one_or_none()
            if not model:
                axis_report["valid"] = False
                axis_report["controls"][cdef["label"]] = {"error": "missing model"}
                continue
            run = (
                await db.execute(
                    select(Run)
                    .where(
                        Run.model_id == model.id,
                        Run.suite_id == suite.id,
                        Run.status == RunStatus.COMPLETED,
                    )
                    .options(selectinload(Run.results))
                    .order_by(Run.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not run or not run.results:
                axis_report["valid"] = False
                axis_report["controls"][cdef["label"]] = {"error": "no completed run"}
                continue
            res: Result = run.results[0]
            score = res.score
            n = res.n_items or 0
            ok = _bound_ok(cdef["label"], axis, score, n)
            axis_report["controls"][cdef["label"]] = {
                "score": score,
                "n": n,
                "ok": ok,
                "run_id": run.id,
            }
            if not ok:
                axis_report["valid"] = False

        status = "valid" if axis_report["valid"] else "invalid"
        key = _scorer_key(axis_key, version)
        existing = await db.get(SettingEntry, key)
        if existing:
            existing.value = status
        else:
            db.add(SettingEntry(key=key, value=status))
        axis_report["status"] = status
        report["suites"][axis_key] = axis_report
        if not axis_report["valid"]:
            report["all_valid"] = False

    await db.commit()
    return report


async def get_scorer_status_map(db: AsyncSession) -> dict[str, str]:
    """Map axis -> valid|invalid|unknown for current suite versions."""
    suites = (await db.execute(select(BenchmarkSuite))).scalars().all()
    out: dict[str, str] = {}
    for suite in suites:
        if suite.axis == BenchmarkAxis.SPEED:
            out[suite.axis.value] = "valid"
            continue
        key = _scorer_key(suite.axis.value, suite.suite_version)
        entry = await db.get(SettingEntry, key)
        out[suite.axis.value] = entry.value if entry and entry.value else "unknown"
    return out


async def run_controls(
    db: AsyncSession,
    *,
    tier: RunTier = RunTier.STANDARD,
) -> dict[str, Any]:
    """Execute null/random/echo against every control axis at the given tier."""
    from benchbase.db.session import get_session_factory
    from benchbase.run_executor import execute_run
    from benchbase.runners.registry import runner_registry

    models = await ensure_control_models(db)
    await db.commit()
    suites = (await db.execute(select(BenchmarkSuite))).scalars().all()
    by_axis = {s.axis: s for s in suites}
    created: list[int] = []

    for model in models:
        for axis in CONTROL_AXES:
            suite = by_axis.get(axis)
            if not suite:
                continue
            meta = {
                "control": True,
                "control_label": model.quantization,
                "eval_mode": "batch",
                "tier": tier.value,
            }
            run = Run(
                model_id=model.id,
                suite_id=suite.id,
                run_group_id=f"controls-{tier.value}",
                tier=tier,
                status=RunStatus.PENDING,
                metadata_json=json.dumps(meta),
                suite_versions_json=json.dumps({suite.axis.value: suite.suite_version}),
                config_json=json.dumps({"control": True, "model": model.name}),
            )
            db.add(run)
            await db.flush()
            created.append(run.id)
    await db.commit()

    factory = get_session_factory()
    for run_id in created:
        async with factory() as lookup:
            run = await lookup.get(Run, run_id, options=[selectinload(Run.suite)])
            if not run or not run.suite:
                continue
            runner_cls = runner_registry.get(run.suite.runner_class)
            if not runner_cls:
                logger.error("No runner for %s", run.suite.runner_class)
                continue
            rc = runner_cls
        await execute_run(run_id, rc)

    async with factory() as db2:
        report = await evaluate_control_bounds(db2)
    report["runs_created"] = created
    return report
