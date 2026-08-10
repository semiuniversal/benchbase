"""Shared operational ledger schema for publishable suite side-cars (Phase B)."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class OperationalLedger:
    """Side-car ledger attached to Harbor/τ² (and any native harness) runs."""

    suite_engine: str  # harbor | tau2 | omp
    suite_name: str
    wall_seconds: float = 0.0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_thinking: int = 0
    success: bool | None = None
    native_metrics: dict[str, Any] = field(default_factory=dict)
    package_hash: str = "placeholder-until-estimator-store"
    litellm_profile: str | None = None
    harness_version: str | None = None
    hardware_note: str | None = None
    t_eff: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens_total(self) -> int:
        return self.tokens_prompt + self.tokens_completion + self.tokens_thinking

    def derive_teff(self, *, mean_wall: float | None = None, p_success: float | None = None) -> float | None:
        """Derive T_eff when native success bits are available."""
        p = p_success
        if p is None and self.success is not None:
            p = 1.0 if self.success else 0.0
        wall = mean_wall if mean_wall is not None else self.wall_seconds
        if p is None or p <= 0:
            self.t_eff = None
            return None
        self.t_eff = wall / p
        return self.t_eff

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tokens_total"] = self.tokens_total
        return d

    def write_json(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return p


class LedgerTimer:
    """Context manager to capture wall seconds for a native subprocess."""

    def __init__(self) -> None:
        self.start = 0.0
        self.elapsed = 0.0

    def __enter__(self) -> LedgerTimer:
        self.start = time.monotonic()
        return self

    def __exit__(self, *args: object) -> None:
        self.elapsed = time.monotonic() - self.start
