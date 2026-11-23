"""Record checkpoint evidence without altering historic scores (WP3)."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import EvidenceObservation, ResultItem, Run
from benchbase.evidence.deployment import ensure_synthetic_revision
from benchbase.evidence.store import write_observation_manifest

logger = logging.getLogger(__name__)


async def record_item_evidence(
    db: AsyncSession,
    *,
    run: Run,
    item: ResultItem,
    row: dict[str, Any],
) -> EvidenceObservation | None:
    """Write manifest + DB row; failures must not break the benchmark run."""
    try:
        rev = await ensure_synthetic_revision(db, run.model_id)
        payload = {
            "schema_version": "benchbase.observation.v1",
            "run_id": run.id,
            "model_id": run.model_id,
            "item_id": item.item_id,
            "passed": item.passed,
            "raw_answer": row.get("raw_answer"),
            "latency_ms": row.get("latency_ms"),
            "detail": json.loads(item.detail_json) if item.detail_json else {},
            "llm_evidence": row.get("llm_evidence"),
            "evaluator_note": (
                "full_llm_exchange"
                if row.get("llm_evidence")
                else "partial; legacy rows may lack llm_evidence"
            ),
        }
        rel, digest = write_observation_manifest(run.id, item.item_id, payload)
        obs = EvidenceObservation(
            run_id=run.id,
            deployment_revision_id=rev.id,
            item_id=item.item_id,
            manifest_path=rel,
            content_hash=digest,
            schema_version="v1",
        )
        db.add(obs)
        await db.flush()
        return obs
    except Exception:
        logger.exception(
            "record_item_evidence failed run_id=%s item_id=%s",
            run.id,
            item.item_id,
        )
        return None