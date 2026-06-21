"""SQLAlchemy ORM models."""

from __future__ import annotations

import datetime
import enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BenchmarkCategory(str, enum.Enum):
    SPEED = "speed"
    CODING = "coding"
    TOOL_USE = "tool_use"
    REASONING = "reasoning"


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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    discovered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    last_checked: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)

    runs: Mapped[list[Run]] = relationship(back_populates="model")


class BenchmarkSuite(Base):
    __tablename__ = "benchmark_suites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[BenchmarkCategory] = mapped_column(
        Enum(BenchmarkCategory), nullable=False
    )
    runner_class: Mapped[str] = mapped_column(String(255), nullable=False)
    config_json: Mapped[Optional[str]] = mapped_column(Text)

    runs: Mapped[list[Run]] = relationship(back_populates="suite")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id"), nullable=False)
    suite_id: Mapped[int] = mapped_column(ForeignKey("benchmark_suites.id"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus), default=RunStatus.PENDING, nullable=False
    )
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
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
    raw_output_json: Mapped[Optional[str]] = mapped_column(Text)
    metrics_json: Mapped[Optional[str]] = mapped_column(Text)

    run: Mapped[Run] = relationship(back_populates="results")


class SettingEntry(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
