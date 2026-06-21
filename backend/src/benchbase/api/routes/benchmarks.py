"""Benchmark run management routes."""

from __future__ import annotations

import datetime
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.db.models import BenchmarkSuite, Model, Run, RunStatus
from benchbase.db.session import get_db
from benchbase.runners.registry import runner_registry

router = APIRouter()


class RunCreate(BaseModel):
    model_id: int
    suite_id: int
    metadata: dict | None = None


class RunOut(BaseModel):
    id: int
    model_id: int
    suite_id: int
    status: str
    started_at: str | None
    completed_at: str | None

    model_config = {"from_attributes": True}


@router.post("/runs", response_model=RunOut)
async def create_run(body: RunCreate, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, body.model_id)
    if not model:
        raise HTTPException(404, "Model not found")
    suite = await db.get(BenchmarkSuite, body.suite_id)
    if not suite:
        raise HTTPException(404, "Benchmark suite not found")

    run = Run(
        model_id=body.model_id,
        suite_id=body.suite_id,
        status=RunStatus.PENDING,
        metadata_json=json.dumps(body.metadata) if body.metadata else None,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


@router.get("/runs", response_model=list[RunOut])
async def list_runs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Run).order_by(Run.id.desc()).limit(50))
    return result.scalars().all()


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/runs/{run_id}/start")
async def start_run(run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id, options=[selectinload(Run.suite), selectinload(Run.model)])
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != RunStatus.PENDING:
        raise HTTPException(400, f"Run is already {run.status.value}")

    runner_cls = runner_registry.get(run.suite.runner_class)
    if not runner_cls:
        raise HTTPException(400, f"Unknown runner: {run.suite.runner_class}")

    run.status = RunStatus.RUNNING
    run.started_at = datetime.datetime.now(datetime.UTC)
    await db.commit()

    try:
        runner = runner_cls()
        await runner.run(run, db)
        run.status = RunStatus.COMPLETED
    except Exception as exc:
        run.status = RunStatus.FAILED
        run.metadata_json = json.dumps({"error": str(exc)})
    finally:
        run.completed_at = datetime.datetime.now(datetime.UTC)
        await db.commit()

    return {"status": run.status.value}


class SuiteOut(BaseModel):
    id: int
    name: str
    category: str
    runner_class: str

    model_config = {"from_attributes": True}


@router.get("/suites", response_model=list[SuiteOut])
async def list_suites(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BenchmarkSuite))
    return result.scalars().all()
