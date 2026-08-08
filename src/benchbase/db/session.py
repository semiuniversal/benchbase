"""Database session factory and initialization (BenchBase v2)."""

from __future__ import annotations

import datetime
import hashlib
import json
import logging

from sqlalchemy import event, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from benchbase.base_model import infer_quant_rank, parse_base_model
from benchbase.config import load_settings
from benchbase.db.models import (
    Base,
    BenchmarkAxis,
    BenchmarkSuite,
    Model,
    ModelStatus,
    Run,
    RunStatus,
)
from benchbase.model_colors import pick_model_color

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None

V2_SCHEMA_FLAG = "v2_schema"

SPEED_SUITE_CONFIG = {
    "pp": [128],
    "tg": [2048],
    "tokenizer": "gpt2",
    "passes": {"smoke": 3, "standard": 3, "thorough": 5},
}

SMOKE_SUITE_CONFIG = {
    "checks": [
        "coherency",
        "code_extract",
        "json_parse",
        "tool_call_syntax",
        "mc_letter",
    ],
    "items_per_check": 5,
}

# Tier item budgets (fixed sets versioned with suite).
_TIER_N = {"smoke": 5, "standard": 100, "thorough": 300}

_DEFAULT_SUITES: list[dict] = [
    {
        "name": "Smoke (Coherency)",
        "axis": BenchmarkAxis.SMOKE,
        "category": BenchmarkAxis.SMOKE,
        "runner_class": "smoke",
        "suite_version": "v1",
        "config_json": json.dumps(SMOKE_SUITE_CONFIG),
    },
    {
        "name": "Speed / Throughput",
        "axis": BenchmarkAxis.SPEED,
        "category": BenchmarkAxis.SPEED,
        "runner_class": "speed",
        "suite_version": "v1",
        "config_json": json.dumps(SPEED_SUITE_CONFIG),
    },
    {
        "name": "Knowledge (tinyMMLU)",
        "axis": BenchmarkAxis.KNOWLEDGE,
        "category": BenchmarkAxis.KNOWLEDGE,
        "runner_class": "knowledge",
        "suite_version": "v1",
        "config_json": json.dumps({"dataset": "tiny_mmlu", "tier_n": _TIER_N}),
    },
    {
        "name": "Reasoning (tinyARC)",
        "axis": BenchmarkAxis.REASONING,
        "category": BenchmarkAxis.REASONING,
        "runner_class": "reasoning",
        "suite_version": "v1",
        "config_json": json.dumps({"dataset": "tiny_arc", "tier_n": _TIER_N}),
    },
    {
        "name": "Math (tinyGSM8K)",
        "axis": BenchmarkAxis.MATH,
        "category": BenchmarkAxis.MATH,
        "runner_class": "math",
        "suite_version": "v1",
        "config_json": json.dumps({"dataset": "tiny_gsm8k", "tier_n": _TIER_N}),
    },
    {
        "name": "Coding (LiveCodeBench)",
        "axis": BenchmarkAxis.CODING,
        "category": BenchmarkAxis.CODING,
        "runner_class": "coding",
        "suite_version": "v1",
        "config_json": json.dumps(
            {"dataset": "livecodebench", "tier_n": {"smoke": 5, "standard": 40, "thorough": 50}}
        ),
    },
    {
        "name": "Tool Calling (BFCL)",
        "axis": BenchmarkAxis.TOOL_CALLING,
        "category": BenchmarkAxis.TOOL_CALLING,
        "runner_class": "tool_calling",
        "suite_version": "v1",
        "config_json": json.dumps(
            {
                "dataset": "bfcl",
                "tier_n": {"smoke": 5, "standard": 125, "thorough": 250},
                "categories": [
                    "simple",
                    "multiple",
                    "parallel",
                    "irrelevance",
                    "multi_turn",
                ],
            }
        ),
    },
    {
        "name": "Instruction Following (IFEval)",
        "axis": BenchmarkAxis.INSTRUCTION,
        "category": BenchmarkAxis.INSTRUCTION,
        "runner_class": "instruction",
        "suite_version": "v1",
        "config_json": json.dumps(
            {"dataset": "ifeval", "tier_n": {"smoke": 5, "standard": 50, "thorough": 100}}
        ),
    },
    {
        "name": "Structured Output",
        "axis": BenchmarkAxis.STRUCTURED,
        "category": BenchmarkAxis.STRUCTURED,
        "runner_class": "structured",
        "suite_version": "v1",
        "config_json": json.dumps(
            {"dataset": "structured_v1", "tier_n": {"smoke": 5, "standard": 30, "thorough": 30}}
        ),
    },
    {
        "name": "Long Context (NIAH)",
        "axis": BenchmarkAxis.LONG_CONTEXT,
        "category": BenchmarkAxis.LONG_CONTEXT,
        "runner_class": "long_context",
        "suite_version": "v1",
        "config_json": json.dumps(
            {
                "dataset": "ruler_niah",
                "lengths_standard": [8000, 16000],
                "lengths_thorough": [8000, 16000, 32000],
                "tasks_per_length": 20,
            }
        ),
    },
]


def _content_hash(cfg: str | None) -> str:
    return hashlib.sha256((cfg or "").encode()).hexdigest()[:16]


def _get_engine():
    global _engine
    if _engine is None:
        settings = load_settings()
        url = settings.database_url
        connect_args: dict = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_async_engine(url, echo=False, connect_args=connect_args)

        if url.startswith("sqlite"):
            @event.listens_for(_engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_connection, connection_record) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=10000")
                cursor.close()

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(_get_engine(), expire_on_commit=False)
    return _session_factory


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async database session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


def _needs_v2_wipe(connection) -> bool:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if "runs" not in tables:
        return False
    if "result_items" not in tables:
        return True
    if "benchmark_suites" in tables:
        cols = {c["name"] for c in inspector.get_columns("benchmark_suites")}
        if "suite_version" not in cols or "axis" not in cols:
            return True
    if "models" in tables:
        cols = {c["name"] for c in inspector.get_columns("models")}
        if "status" not in cols or "base_model" not in cols:
            return True
    if "runs" in tables:
        cols = {c["name"] for c in inspector.get_columns("runs")}
        if "tier" not in cols or "run_group_id" not in cols:
            return True
    return False


def _wipe_run_data(connection) -> None:
    """Clean-break: drop empirical tables; keep models registry rows."""
    logger.warning("BenchBase v2 clean break: wiping runs, results, and suites")
    for table in ("result_items", "results", "runs", "benchmark_suites"):
        connection.execute(text(f"DROP TABLE IF EXISTS {table}"))


def _migrate_models_v2_columns(connection) -> None:
    inspector = inspect(connection)
    if "models" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("models")}
    alters = []
    if "color" not in columns:
        alters.append("ADD COLUMN color VARCHAR(32) DEFAULT 'blue'")
    if "status" not in columns:
        alters.append("ADD COLUMN status VARCHAR(16) DEFAULT 'unreachable'")
    if "base_model" not in columns:
        alters.append("ADD COLUMN base_model VARCHAR(255)")
    if "quant_rank" not in columns:
        alters.append("ADD COLUMN quant_rank INTEGER")
    for clause in alters:
        connection.execute(text(f"ALTER TABLE models {clause}"))


async def init_db() -> None:
    """Create/migrate v2 schema, wipe legacy runs if needed, seed suites."""
    engine = _get_engine()
    async with engine.begin() as conn:
        wipe = await conn.run_sync(_needs_v2_wipe)
        if wipe:
            await conn.run_sync(_wipe_run_data)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_models_v2_columns)

    async with get_session_factory()() as session:
        await _assign_missing_model_fields(session)
        # Replace suite catalog with v2 definitions when empty or after wipe.
        existing = (
            await session.execute(select(BenchmarkSuite))
        ).scalars().all()
        existing_names = {s.name for s in existing}
        expected_names = {s["name"] for s in _DEFAULT_SUITES}
        if existing_names != expected_names:
            for suite in existing:
                await session.delete(suite)
            await session.flush()
            for suite_def in _DEFAULT_SUITES:
                row = dict(suite_def)
                row["content_hash"] = _content_hash(row.get("config_json"))
                session.add(BenchmarkSuite(**row))
        else:
            for suite in existing:
                if not suite.content_hash:
                    suite.content_hash = _content_hash(suite.config_json)
        await _recover_stale_running_runs(session)
        await session.commit()


async def _recover_stale_running_runs(session: AsyncSession) -> None:
    result = await session.execute(select(Run).where(Run.status == RunStatus.RUNNING))
    runs = list(result.scalars().all())
    if not runs:
        return
    now = datetime.datetime.now(datetime.UTC)
    msg = "Interrupted by server restart. Run the benchmark again."
    for run in runs:
        run.status = RunStatus.FAILED
        run.completed_at = now
        try:
            meta = json.loads(run.metadata_json) if run.metadata_json else {}
        except json.JSONDecodeError:
            meta = {}
        meta["error"] = msg
        run.metadata_json = json.dumps(meta)


async def _assign_missing_model_fields(session: AsyncSession) -> None:
    result = await session.execute(select(Model).order_by(Model.id))
    models = list(result.scalars().all())
    used = {m.color for m in models if m.color}
    for model in models:
        if not model.color:
            model.color = pick_model_color(used)
            used.add(model.color)
        if not model.base_model:
            model.base_model = parse_base_model(model.name)
        if model.quant_rank is None:
            model.quant_rank = infer_quant_rank(model.name, model.quantization)
        # Prefer existing status; otherwise derive from legacy is_active.
        if model.status is None:
            model.set_status(
                ModelStatus.ACTIVE if model.is_active else ModelStatus.UNREACHABLE
            )
        else:
            # Keep is_active mirror in sync.
            model.is_active = model.status == ModelStatus.ACTIVE
            # First v2 boot: map previously-active rows that still say unreachable default
            # only when is_active was true and status is the column default.
            if model.is_active and model.status == ModelStatus.UNREACHABLE:
                # is_active column may still be true from v1 while status defaulted unreachable
                pass
        # Heal v1→v2: if is_active True but status unreachable (default), promote to active
        # only when last_checked exists (was health-checked as live).
        if (
            model.status == ModelStatus.UNREACHABLE
            and bool(model.is_active)
            and model.last_checked is not None
        ):
            model.set_status(ModelStatus.ACTIVE)
        elif model.status == ModelStatus.UNREACHABLE and not model.is_active:
            model.is_active = False
        else:
            model.is_active = model.status == ModelStatus.ACTIVE
