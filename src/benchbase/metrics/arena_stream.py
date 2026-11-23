"""Arena stream metric accumulation with explicit provenance (WP2)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArenaStreamAccumulator:
    start: float = field(default_factory=time.perf_counter)
    first_output_time: float | None = None
    output_chunk_count: int = 0
    thinking_chunk_count: int = 0
    provider_completion_tokens: int | None = None
    provider_total_tokens: int | None = None

    def note_chunk(self, kind: str) -> None:
        now = time.perf_counter()
        if kind == "thinking":
            self.thinking_chunk_count += 1
        elif kind == "content":
            if self.first_output_time is None:
                self.first_output_time = now - self.start
            self.output_chunk_count += 1

    def note_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        comp = usage.get("completion_tokens")
        total = usage.get("total_tokens")
        if isinstance(comp, int) and comp >= 0:
            self.provider_completion_tokens = comp
        if isinstance(total, int) and total >= 0:
            self.provider_total_tokens = total

    def snapshot(self) -> dict[str, Any]:
        now = time.perf_counter()
        elapsed = now - self.start
        output_elapsed = (
            (now - self.start) - self.first_output_time
            if self.first_output_time is not None
            else None
        )
        chunk_rate = (
            round(self.output_chunk_count / output_elapsed, 2)
            if output_elapsed and output_elapsed > 0
            else None
        )
        # Arena chat lacks per-token timestamps; never label chunk or usage heuristics as decode TPS.
        decode_tps: float | None = None
        decode_method = "unavailable"
        output_tokens: int | None = (
            self.provider_completion_tokens
            if self.provider_completion_tokens is not None
            else None
        )

        return {
            "output_ttft": round(self.first_output_time, 4)
            if self.first_output_time is not None
            else None,
            "output_chunk_count": self.output_chunk_count,
            "thinking_chunk_count": self.thinking_chunk_count,
            "output_tokens": output_tokens,
            "tokens_per_second": decode_tps,
            "decode_rate_method": decode_method,
            "output_chunk_rate_per_s": chunk_rate,
            "output_chunk_rate_method": "stream_chunks",
            "elapsed": round(elapsed, 4),
            "provider_total_tokens": self.provider_total_tokens,
        }