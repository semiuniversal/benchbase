"""Database session factory and initialization."""

from __future__ import annotations

import datetime
import json

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from benchbase.config import load_settings
from benchbase.db.models import Base, BenchmarkCategory, BenchmarkSuite, Model, Run, RunStatus
from benchbase.model_colors import pick_model_color

_engine = None
_session_factory = None

REASONING_SUITE_CONFIG = {
    "tasks": [
        "gsm8k",
        "arc_easy",
        "hellaswag",
        "mmlu_high_school_mathematics",
    ],
    "num_concurrent": 1,
    "tokenizer": "gpt2",
    "timeout": 3600,
    "eos_string": "",
}

SPEED_SUITE_CONFIG = {
    "pp": [128],
    "tg": [2048],
    "tokenizer": "gpt2",
}

_DEFAULT_SUITES = [
    {
        "name": "Speed / Throughput",
        "category": BenchmarkCategory.SPEED,
        "runner_class": "speed",
        "config_json": json.dumps(SPEED_SUITE_CONFIG),
    },
    {
        "name": "Coding (HumanEval)",
        "category": BenchmarkCategory.CODING,
        "runner_class": "coding",
    },
    {
        "name": "Tool Use",
        "category": BenchmarkCategory.TOOL_USE,
        "runner_class": "tool_use",
    },
    {
        "name": "Reasoning (GSM8K / MMLU)",
        "category": BenchmarkCategory.REASONING,
        "runner_class": "reasoning",
        "config_json": json.dumps(REASONING_SUITE_CONFIG),
    },
]


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


async def init_db() -> None:
    """Create all tables, migrate schema, and seed benchmark suites on startup."""
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_models_color_column)

    async with get_session_factory()() as session:
        await _assign_missing_model_colors(session)
        for suite_def in _DEFAULT_SUITES:
            result = await session.execute(
                select(BenchmarkSuite).where(BenchmarkSuite.name == suite_def["name"])
            )
            if not result.scalar_one_or_none():
                session.add(BenchmarkSuite(**suite_def))
        await _migrate_reasoning_suite_config(session)
        await _migrate_speed_suite_config(session)
        await _recover_stale_running_runs(session)
        await session.commit()


async def _recover_stale_running_runs(session: AsyncSession) -> None:
    """Runs left RUNNING after a crash/reload cannot still be executing."""
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


async def _migrate_speed_suite_config(session: AsyncSession) -> None:
    result = await session.execute(
        select(BenchmarkSuite).where(BenchmarkSuite.runner_class == "speed")
    )
    suite = result.scalar_one_or_none()
    if not suite:
        return

    if not suite.config_json:
        suite.config_json = json.dumps(SPEED_SUITE_CONFIG)
        return

    try:
        cfg = json.loads(suite.config_json)
    except json.JSONDecodeError:
        suite.config_json = json.dumps(SPEED_SUITE_CONFIG)
        return

    tg = cfg.get("tg")
    if tg == [32] or tg == 32:
        cfg["tg"] = [2048]
        suite.config_json = json.dumps(cfg)
    elif not tg:
        cfg["tg"] = [2048]
        suite.config_json = json.dumps(cfg)


async def _migrate_reasoning_suite_config(session: AsyncSession) -> None:
    result = await session.execute(
        select(BenchmarkSuite).where(BenchmarkSuite.runner_class == "reasoning")
    )
    suite = result.scalar_one_or_none()
    if not suite:
        return

    if not suite.config_json:
        suite.config_json = json.dumps(REASONING_SUITE_CONFIG)
        return

    try:
        cfg = json.loads(suite.config_json)
    except json.JSONDecodeError:
        suite.config_json = json.dumps(REASONING_SUITE_CONFIG)
        return

    tasks = cfg.get("tasks", [])
    if "mmlu" in tasks:
        cfg["tasks"] = [t for t in tasks if t != "mmlu"]
        if "mmlu_high_school_mathematics" not in cfg["tasks"]:
            cfg["tasks"].append("mmlu_high_school_mathematics")
        suite.config_json = json.dumps(cfg)

    # Drop default sample cap — full runs should not pass lm-eval --limit.
    if cfg.get("limit") == 20:
        cfg.pop("limit", None)
        suite.config_json = json.dumps(cfg)


def _migrate_models_color_column(connection) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(connection)
    if "models" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("models")}
    if "color" not in columns:
        connection.execute(text("ALTER TABLE models ADD COLUMN color VARCHAR(32)"))


async def _assign_missing_model_colors(session: AsyncSession) -> None:
    result = await session.execute(select(Model).order_by(Model.id))
    models = list(result.scalars().all())
    used = {m.color for m in models if m.color}
    for model in models:
        if not model.color:
            model.color = pick_model_color(used)
            used.add(model.color)
