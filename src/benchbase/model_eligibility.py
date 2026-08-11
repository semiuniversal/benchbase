"""Finalist / tier eligibility helpers for models."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import (
    BenchmarkAxis,
    Model,
    ModelStatus,
    Run,
    RunStatus,
    RunTier,
)


async def _group_fully_completed(db: AsyncSession, run_group_id: str) -> bool:
    result = await db.execute(select(Run).where(Run.run_group_id == run_group_id))
    members = list(result.scalars().all())
    if not members:
        return False
    return all(m.status == RunStatus.COMPLETED for m in members)


async def model_has_completed_tier(
    db: AsyncSession,
    model_id: int,
    tier: RunTier,
) -> bool:
    """True if the model has a fully completed tier group at `tier` or higher.

    Thorough counts as past Standard. Solo runs without run_group_id count when
    status is completed and tier matches.
    """
    wanted = {tier}
    if tier == RunTier.STANDARD:
        wanted.add(RunTier.THOROUGH)
    if tier == RunTier.SMOKE:
        wanted.update({RunTier.STANDARD, RunTier.THOROUGH})

    result = await db.execute(
        select(Run)
        .where(
            Run.model_id == model_id,
            Run.status == RunStatus.COMPLETED,
            Run.tier.in_(wanted),
        )
        .options(selectinload(Run.suite))
        .order_by(Run.id.desc())
        .limit(40)
    )
    for run in result.scalars().all():
        # Agentic finalist rows use tier=thorough but are not a Standard batch.
        if run.suite and run.suite.axis == BenchmarkAxis.AGENTIC:
            continue
        try:
            import json

            meta = json.loads(run.metadata_json) if run.metadata_json else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}
        if meta.get("finalist"):
            continue
        if run.run_group_id:
            if await _group_fully_completed(db, run.run_group_id):
                return True
            continue
        # Solo completed tier run (rare) still counts.
        return True
    return False


async def model_finalist_eligible(db: AsyncSession, model_id: int) -> bool:
    return await model_has_completed_tier(db, model_id, RunTier.STANDARD)


async def list_finalist_eligible_models(db: AsyncSession) -> list[Model]:
    result = await db.execute(
        select(Model)
        .where(Model.status == ModelStatus.ACTIVE)
        .order_by(Model.name)
    )
    models = list(result.scalars().all())
    eligible: list[Model] = []
    for m in models:
        if await model_finalist_eligible(db, m.id):
            eligible.append(m)
    return eligible
