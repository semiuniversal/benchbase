"""Deployment revision helpers (WP3)."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import DeploymentRevision, Model


async def ensure_synthetic_revision(db: AsyncSession, model_id: int) -> DeploymentRevision:
    stmt = (
        select(DeploymentRevision)
        .where(
            DeploymentRevision.model_id == model_id,
            DeploymentRevision.synthetic_legacy.is_(True),
        )
        .limit(1)
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    model = await db.get(Model, model_id)
    fp = {
        "model_name": model.name if model else None,
        "endpoint_url": model.endpoint_url if model else None,
        "provenance": "synthetic_legacy_vnext",
    }
    rev = DeploymentRevision(
        model_id=model_id,
        fingerprint_json=json.dumps(fp),
        synthetic_legacy=True,
    )
    db.add(rev)
    await db.flush()
    return rev