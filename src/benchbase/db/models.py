"""SQLAlchemy ORM models (BenchBase v2)."""

from __future__ import annotations

import datetime
import enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from benchbase.model_colors import DEFAULT_MODEL_COLOR


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    return [e.value for e in enum_cls]


class Base(DeclarativeBase):
    pass


class ModelStatus(str, enum.Enum):
    ACTIVE = "active"
    UNREACHABLE = "unreachable"
    ARCHIVED = "archived"


class BenchmarkAxis(str, enum.Enum):
    SPEED = "speed"
    KNOWLEDGE = "knowledge"
    REASONING = "reasoning"
    MATH = "math"
    CODING = "coding"
    TOOL_CALLING = "tool_calling"
    INSTRUCTION = "instruction"
    STRUCTURED = "structured"
    LONG_CONTEXT = "long_context"
    SMOKE = "smoke"


# Backward-compatible alias used by older imports during transition.
BenchmarkCategory = BenchmarkAxis


class RunTier(str, enum.Enum):
    SMOKE = "smoke"
    STANDARD = "standard"
    THOROUGH = "thorough"


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Model(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(512), nullable=False)
    backend_runtime: Mapped[Optional[str]] = mapped_column(String(128))
    quantization: Mapped[Optional[str]] = mapped_column(String(64))
    host: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[ModelStatus] = mapped_column(
        Enum(ModelStatus, values_callable=_enum_values, native_enum=False),
        default=ModelStatus.UNREACHABLE,
        server_default="unreachable",
        nullable=False,
    )
    # Kept in sync with status == active for older readers; prefer `status`.
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    color: Mapped[str] = mapped_column(
        String(32), default=DEFAULT_MODEL_COLOR, server_default="blue"
    )
    base_model: Mapped[Optional[str]] = mapped_column(String(255))
    quant_rank: Mapped[Optional[int]] = mapped_column(Integer)
    discovered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    last_checked: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    runs: Mapped[list[Run]] = relationship(back_populates="model")

    def set_status(self, status: ModelStatus) -> None:
        self.status = status
        self.is_active = status == ModelStatus.ACTIVE


class BenchmarkSuite(Base):
    __tablename__ = "benchmark_suites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    axis: Mapped[BenchmarkAxis] = mapped_column(
        Enum(BenchmarkAxis, values_callable=_enum_values, native_enum=False),
        nullable=False,
    )
    # Legacy column name kept as synonym for axis for older code paths.
    category: Mapped[BenchmarkAxis] = mapped_column(
        Enum(BenchmarkAxis, values_callable=_enum_values, native_enum=False),
        nullable=False,
    )
    runner_class: Mapped[str] = mapped_column(String(255), nullable=False)
    suite_version: Mapped[str] = mapped_column(String(32), default="v1", server_default="v1")
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    config_json: Mapped[Optional[str]] = mapped_column(Text)

    runs: Mapped[list[Run]] = relationship(back_populates="suite")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    suite_id: Mapped[int] = mapped_column(
        ForeignKey("benchmark_suites.id"), nullable=False
    )
    run_group_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    tier: Mapped[RunTier] = mapped_column(
        Enum(RunTier, values_callable=_enum_values, native_enum=False),
        default=RunTier.STANDARD,
        nullable=False,
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, values_callable=_enum_values, native_enum=False),
        default=RunStatus.PENDING,
        nullable=False,
    )
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    config_json: Mapped[Optional[str]] = mapped_column(Text)
    suite_versions_json: Mapped[Optional[str]] = mapped_column(Text)
    smoke_override: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    metadata_json: Mapped[Optional[str]] = mapped_column(Text)

    model: Mapped[Model] = relationship(back_populates="runs")
    suite: Mapped[BenchmarkSuite] = relationship(back_populates="runs")
    results: Mapped[list[Result]] = relationship(back_populates="run")


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    task_name: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[Optional[float]] = mapped_column(Float)
    ci_low: Mapped[Optional[float]] = mapped_column(Float)
    ci_high: Mapped[Optional[float]] = mapped_column(Float)
    n_items: Mapped[Optional[int]] = mapped_column(Integer)
    primary_method: Mapped[Optional[str]] = mapped_column(String(32))
    raw_output_json: Mapped[Optional[str]] = mapped_column(Text)
    metrics_json: Mapped[Optional[str]] = mapped_column(Text)

    run: Mapped[Run] = relationship(back_populates="results")
    items: Mapped[list[ResultItem]] = relationship(back_populates="result")


class ResultItem(Base):
    __tablename__ = "result_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    result_id: Mapped[int] = mapped_column(ForeignKey("results.id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String(128), nullable=False)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean)
    raw_answer: Mapped[Optional[str]] = mapped_column(Text)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    detail_json: Mapped[Optional[str]] = mapped_column(Text)

    result: Mapped[Result] = relationship(back_populates="items")


class SettingEntry(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
