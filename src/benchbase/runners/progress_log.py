"""Progress logging into RunLogManager for live tier feeds."""

from __future__ import annotations

import json
import time
from typing import Any

from benchbase.run_log import RunLogManager, run_log_context

# Keep each exchange readable in the run window without dumping haystacks.
QA_MAX_CHARS = 500


def _clip(text: str, limit: int = QA_MAX_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def item_question(item: dict[str, Any]) -> str:
    """Question text for the live log.

    Long-context items contribute the prompt template (or the needle when that
    is all there is), never the buried document.
    """
    needle = item.get("needle")
    if needle:
        template = str(item.get("prompt_template") or "").strip()
        if template:
            return template
        return str(needle)
    return str(item.get("prompt") or "")


def item_expected(item: dict[str, Any]) -> str | None:
    """Short expected value when the item has one."""
    if item.get("needle"):
        return str(item["needle"])
    answer = item.get("answer")
    if answer is not None and str(answer).strip():
        return str(answer)
    name = item.get("expected_name")
    if name:
        args = item.get("expected_args")
        if args:
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            return f"{name}({args})"
        return str(name)
    return None


def _verdict(row: dict[str, Any]) -> str:
    if row.get("scorer_error"):
        return "ERROR"
    if row.get("passed"):
        return "PASS"
    return "FAIL"


def _answer_text(row: dict[str, Any]) -> str:
    raw = row.get("raw_answer")
    if raw is not None and str(raw).strip():
        return str(raw)
    extracted = row.get("extracted")
    if extracted is not None and str(extracted).strip():
        return str(extracted)
    return "(empty)"


def format_exchange(
    done: int,
    total: int,
    row: dict[str, Any],
    question: str | None,
    expected: str | None,
) -> str:
    """One item as a verdict line plus question, answer, and expected value."""
    lines = [f"[{done}/{total}] {_verdict(row)} {row.get('item_id')}"]
    if question and question.strip():
        lines.append(f"Q: {_clip(question)}")
    lines.append(f"A: {_clip(_answer_text(row))}")
    if expected is not None and str(expected).strip():
        lines.append(f"expected: {_clip(str(expected))}")
    return "\n".join(lines)


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
        already_done: int = 0,
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
        self.done = max(0, already_done)
        self._last_emit = 0.0
        run_id = run_log_context.get()
        if run_id is not None:
            resume_note = (
                f" · resuming from {already_done}/{total}"
                if already_done
                else ""
            )
            RunLogManager.log(
                run_id,
                f"=== {title} · {total} items · {tier}{resume_note} ===",
            )

    def _run_id(self) -> int | None:
        return run_log_context.get()

    def record(
        self,
        row: dict[str, Any],
        *,
        sample_text: str | None = None,
        expected: str | None = None,
    ) -> None:
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

        RunLogManager.log(
            run_id,
            format_exchange(self.done, self.total, row, sample_text, expected),
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
