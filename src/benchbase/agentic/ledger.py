"""AttemptLedger — operational fields harvested from an OMP attempt."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AttemptLedger:
    """Per-attempt operational ledger (spec §3)."""

    wall_seconds: float = 0.0
    turns: int = 0
    tool_calls: int = 0
    hashline_rejected_edits: int = 0
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_thinking: int = 0
    thrash_cutoffs: int = 0
    spin_cutoffs: int = 0
    timed_out: bool = False
    aborted: bool = False
    session_id: str | None = None
    session_file: str | None = None
    prompt_injected: bool = False
    resolved: bool | None = None
    abstained: bool = False
    cutoff_reason: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens_total(self) -> int:
        return self.tokens_prompt + self.tokens_completion + self.tokens_thinking

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AttemptLedger:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known and k != "extra"}
        extra = dict(data.get("extra") or {})
        for k, v in data.items():
            if k not in known:
                extra[k] = v
        kwargs["extra"] = extra
        return cls(**kwargs)
