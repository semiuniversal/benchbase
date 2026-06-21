"""Plugin registry for benchmark runners."""

from __future__ import annotations

from typing import Type

from benchbase.runners.base import BenchmarkRunner

runner_registry: dict[str, Type[BenchmarkRunner]] = {}


def register_runner(name: str):
    """Decorator to register a runner class by name."""

    def decorator(cls: Type[BenchmarkRunner]):
        runner_registry[name] = cls
        return cls

    return decorator


def _auto_discover():
    """Import all built-in runner modules so their @register_runner decorators fire."""
    from benchbase.runners import speed, coding, tool_use, reasoning  # noqa: F401


_auto_discover()
