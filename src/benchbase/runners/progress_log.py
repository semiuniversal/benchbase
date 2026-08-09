"""Progress logging into RunLogManager for live tier feeds."""

from __future__ import annotations

import time
from typing import Any

from benchbase.run_log import RunLogManager, run_log_context


class AxisProgressLog:
    """Emit honest per-item progress for the live run log."""

    def __init__(
        self,
        *,
        title: str,
        total: int,
        tier: str,
        every_n: int = 5,
        every_s: float = 3.0,
        sample_every: int = 20,
    ) -> None:
        self.title = title
        self.total = total
        self.tier = tier
        self.every_n = max(1, every_n)
        self.every_s = every_s
        self.sample_every = max(1, sample_every)
        self.ok = 0
        self.fail = 0
        self.unparseable = 0
        self.errors = 0
        self.done = 0
        self._last_emit = 0.0
        run_id = run_log_context.get()
        if run_id is not None:
            RunLogManager.log(
                run_id,
                f"=== {title} · {total} items · {tier} ===",
            )

    def _run_id(self) -> int | None:
        return run_log_context.get()

    def record(self, row: dict[str, Any], *, sample_text: str | None = None) -> None:
        self.done += 1
        if row.get("scorer_error"):
            self.errors += 1
        elif row.get("reason") == "unparseable":
            self.unparseable += 1
            self.fail += 1
        elif row.get("passed"):
            self.ok += 1
        else:
            self.fail += 1

        run_id = self._run_id()
        if run_id is None:
            return

        now = time.monotonic()
        should = (
            self.done == 1
            or self.done == self.total
            or self.done % self.every_n == 0
            or (now - self._last_emit) >= self.every_s
        )
        if should:
            RunLogManager.log(
                run_id,
                f"[{self.done}/{self.total}] ok={self.ok} fail={self.fail} "
                f"unparseable={self.unparseable} errors={self.errors}",
            )
            self._last_emit = now

        if sample_text and (self.done == 1 or self.done % self.sample_every == 0):
            extracted = row.get("extracted")
            verdict = (
                "PASS"
                if row.get("passed")
                else ("ERROR" if row.get("scorer_error") else "FAIL")
            )
            snippet = sample_text.replace("\n", " ")[:120]
            extra = f" → {extracted}" if extracted is not None else ""
            RunLogManager.log(
                run_id,
                f"  sample {row.get('item_id')}: {verdict}{extra} | {snippet}",
            )

    def finish(self, score: float | None) -> None:
        run_id = self._run_id()
        if run_id is None:
            return
        score_s = f"{score:.1f}" if score is not None else "—"
        RunLogManager.log(
            run_id,
            f"=== {self.title} done · score={score_s} "
            f"(ok={self.ok}/{self.total}) ===",
        )
