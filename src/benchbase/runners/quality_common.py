"""Shared helpers for v2 quality-axis runners (extract-then-compare)."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Result, ResultItem, Run, RunTier
from benchbase.litellm_client import LiteLLMClient
from benchbase.stats import proportion_score, wilson_interval

logger = logging.getLogger(__name__)

FIXTURES_ROOT = (
    Path(__file__).resolve().parent.parent.parent.parent / "corpus" / "suites"
)
DEFAULT_SUITE_VERSION = "v2"

_TIER_KEY = {
    RunTier.SMOKE: "smoke",
    RunTier.STANDARD: "standard",
    RunTier.THOROUGH: "thorough",
}

CONTROL_MODEL_NAMES = frozenset(
    {"__control_null__", "__control_random__", "__control_echo__"}
)

# Extra API budget so thinking-on models can finish <think> before the visible
# answer. Nothink models EOS after a few tokens, so historical radars stay valid
# — do not re-run the fleet. Re-run only seats that dump thinking into content.
THINKING_HEADROOM = 2048

_THINK_CLOSED = re.compile(r"<think>.*?</think>\s*", re.IGNORECASE | re.DOTALL)
_THINK_OPEN = re.compile(r"<think>.*\Z", re.IGNORECASE | re.DOTALL)
_THINK_PROSE = re.compile(
    r"^(?:here'?s a thinking process|thinking process)\s*:.*?(?:\n\s*\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def visible_completion(message: dict[str, Any] | str | None) -> str:
    """Return the scorable answer, never the thinking stream.

    llama.cpp/Nail often put chain-of-thought in `content` as prose, not
    `reasoning_content`. Scoring that text is how Knowledge went 0/100.
    """
    if message is None:
        return ""
    if isinstance(message, str):
        text = message
    else:
        text = message.get("content") or ""
    text = str(text).strip()
    if not text:
        return ""
    text = _THINK_CLOSED.sub("", text).strip()
    text = _THINK_OPEN.sub("", text).strip()
    if not text:
        return ""
    while True:
        nxt = _THINK_PROSE.sub("", text, count=1).strip()
        if nxt == text or not nxt:
            break
        text = nxt
    return text


def load_fixture_items(axis: str, version: str = DEFAULT_SUITE_VERSION) -> list[dict[str, Any]]:
    path = FIXTURES_ROOT / axis / version / "items.json"
    if not path.exists():
        # Fall back to v1 only if v2 missing (should not happen after remediation).
        path = FIXTURES_ROOT / axis / "v1" / "items.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return list(data.get("items") or [])
    return list(data)


def load_manifest(axis: str, version: str = DEFAULT_SUITE_VERSION) -> dict[str, Any]:
    path = FIXTURES_ROOT / axis / version / "MANIFEST.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def select_tier_items(
    items: list[dict[str, Any]],
    tier: RunTier,
    tier_n: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    key = _TIER_KEY.get(tier, "standard")
    n = (tier_n or {}).get(key)
    if n is None:
        defaults = {"smoke": 5, "standard": 100, "thorough": 300}
        n = defaults.get(key, 100)
    return items[: max(0, min(n, len(items)))]


def extract_mc_letter(text: str) -> tuple[str | None, str | None]:
    """Extract a single committed A–D letter. Returns (letter, reason_if_failed)."""
    if not text or not text.strip():
        return None, "unparseable"
    stripped = text.strip()
    # Leading "A)" / "B." / "C " style commitment (common chat format).
    m = re.match(r"^([A-D])(?:\s*[).:\-]|$)(?:\s|$)", stripped, re.I)
    if m:
        return m.group(1).upper(), None
    # Prefer explicit answer markers toward the end.
    matches = list(
        re.finditer(r"(?:answer|final)\s*(?:is\s*)?[:\-]?\s*([A-D])\b", text, re.I)
    )
    if matches:
        letter = matches[-1].group(1).upper()
        return letter, None
    # Trailing standalone letter on last non-empty line.
    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    if lines:
        m = re.fullmatch(r"([A-D])\.?", lines[-1], re.I)
        if m:
            return m.group(1).upper(), None
        m = re.match(r"^([A-D])(?:\s*[).:\-]|\s|$)", lines[-1], re.I)
        if m:
            return m.group(1).upper(), None
        m = re.search(r"\b([A-D])\b\s*$", lines[-1], re.I)
        if m:
            return m.group(1).upper(), None
    # Multiple distinct letters without a clear commitment → unparseable (F1 guard).
    found = {m.group(1).upper() for m in re.finditer(r"\b([A-D])\b", text)}
    if len(found) == 1:
        compact = re.sub(r"[^A-Za-z]", "", text)
        if len(compact) <= 2:
            return next(iter(found)), None
    return None, "unparseable"


def extract_final_number(text: str) -> tuple[str | None, str | None]:
    """Extract final numeric answer (GSM8K #### or last-line number)."""
    if not text or not text.strip():
        return None, "unparseable"
    cleaned = text.replace(",", "")
    m = re.search(r"####\s*(-?\d+(?:\.\d+)?)", cleaned)
    if m:
        return m.group(1), None
    m = re.search(r"(?:answer|final)\s*(?:is\s*)?[:\-]?\s*(-?\d+(?:\.\d+)?)\b", cleaned, re.I)
    if m:
        return m.group(1), None
    lines = [ln.strip() for ln in cleaned.strip().splitlines() if ln.strip()]
    if lines:
        nums = re.findall(r"-?\d+(?:\.\d+)?", lines[-1])
        if len(nums) == 1:
            return nums[-1], None
        if nums and re.search(r"(?:answer|final|=)\s*$", lines[-1][:- len(nums[-1])], re.I):
            return nums[-1], None
        # Last line is only a number (possibly with units stripped).
        if re.fullmatch(r"-?\d+(?:\.\d+)?", lines[-1]):
            return lines[-1], None
    return None, "unparseable"


def normalize_number(s: str) -> str:
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
        return str(f)
    except Exception:
        return s.strip()


async def chat_once(
    client: LiteLLMClient | None,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 512,
    temperature: float = 0.0,
    *,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[str, float]:
    """Chat completion, or synthetic control response when model is a control."""
    if model in CONTROL_MODEL_NAMES:
        from benchbase.controls import control_respond

        t0 = time.perf_counter()
        text = control_respond(model, messages, tools=tools)
        return text, (time.perf_counter() - t0) * 1000.0

    assert client is not None
    t0 = time.perf_counter()
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens + THINKING_HEADROOM,
        "temperature": temperature,
    }
    if tools is not None:
        kwargs["tools"] = tools
    resp = await client.chat(**kwargs)
    latency = (time.perf_counter() - t0) * 1000.0
    choices = resp.get("choices") or []
    content = ""
    if choices:
        msg = choices[0].get("message") or {}
        content = visible_completion(msg)
        # Prefer tool_calls if present.
        tcalls = msg.get("tool_calls")
        if tcalls and not content:
            try:
                tc = tcalls[0]
                fn = tc.get("function") or {}
                content = json.dumps(
                    {"name": fn.get("name"), "arguments": json.loads(fn.get("arguments") or "{}")}
                )
            except Exception:
                content = json.dumps(tcalls)
    return str(content), latency


async def persist_axis_result(
    db: AsyncSession,
    run: Run,
    task_name: str,
    item_rows: list[dict[str, Any]],
    *,
    primary_method: str = "raw",
    metrics: dict[str, Any] | None = None,
) -> Result:
    """Persist aggregate + per-item rows in one shot (agentic / non-resumable).

    item_rows: item_id, passed, raw_answer?, latency_ms?, reason?, detail?,
    scorer_error?  scorer_error is treated like harness_error: fail, kept in
    the denominator (planned_n).
    """
    result = await ensure_axis_result(
        db,
        run,
        task_name,
        planned_n=len(item_rows),
        primary_method=primary_method,
        metrics=metrics,
        replace_items=True,
    )
    for row in item_rows:
        await checkpoint_item(db, result, row, commit=False)
    await finalize_axis_result(db, result, metrics=metrics)
    return result


def _item_detail(row: dict[str, Any]) -> dict[str, Any]:
    raw_detail = row.get("detail")
    if isinstance(raw_detail, dict):
        detail = dict(raw_detail)
    elif raw_detail is not None:
        detail = {"data": raw_detail}
    else:
        detail = {}
    if row.get("reason"):
        detail["reason"] = row["reason"]
    if row.get("extracted") is not None:
        detail["extracted"] = row["extracted"]
    if row.get("scorer_error"):
        detail["scorer_error"] = True
    return detail


def _passed_value(row: dict[str, Any]) -> bool | None:
    if row.get("scorer_error"):
        return False
    if row.get("passed") is not None:
        return bool(row.get("passed"))
    return None


def _metrics_dict(result: Result) -> dict[str, Any]:
    if not result.metrics_json:
        return {}
    try:
        payload = json.loads(result.metrics_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


async def ensure_axis_result(
    db: AsyncSession,
    run: Run,
    task_name: str,
    *,
    planned_n: int,
    primary_method: str = "raw",
    metrics: dict[str, Any] | None = None,
    replace_items: bool = False,
) -> Result:
    """Create or load the draft Result for a resumable axis."""
    from sqlalchemy import delete, select

    existing = (
        await db.execute(
            select(Result).where(Result.run_id == run.id, Result.task_name == task_name)
        )
    ).scalar_one_or_none()
    base_metrics = {
        "planned_n": planned_n,
        "scored_n": planned_n,
        "n": planned_n,
        "checkpoint": True,
        **(metrics or {}),
    }
    if existing is not None:
        if replace_items:
            await db.execute(delete(ResultItem).where(ResultItem.result_id == existing.id))
            existing.score = None
            existing.ci_low = None
            existing.ci_high = None
            existing.n_items = planned_n
            existing.primary_method = primary_method
            existing.metrics_json = json.dumps(base_metrics)
            await db.flush()
        else:
            # Keep planned_n authoritative for this sitting.
            m = _metrics_dict(existing)
            m["planned_n"] = planned_n
            m["scored_n"] = planned_n
            m["n"] = planned_n
            m["checkpoint"] = True
            if metrics:
                m.update(metrics)
            existing.n_items = planned_n
            existing.metrics_json = json.dumps(m)
            await db.flush()
        return existing

    result = Result(
        run_id=run.id,
        task_name=task_name,
        score=None,
        ci_low=None,
        ci_high=None,
        n_items=planned_n,
        primary_method=primary_method,
        metrics_json=json.dumps(base_metrics),
    )
    db.add(result)
    await db.flush()
    return result


async def load_completed_item_ids(db: AsyncSession, result: Result) -> set[str]:
    from sqlalchemy import select

    rows = (
        await db.execute(select(ResultItem.item_id).where(ResultItem.result_id == result.id))
    ).scalars().all()
    return {str(i) for i in rows}


async def checkpoint_item(
    db: AsyncSession,
    result: Result,
    row: dict[str, Any],
    *,
    commit: bool = True,
) -> ResultItem:
    """Upsert a single ResultItem and optionally commit."""
    from sqlalchemy import select

    item_id = str(row["item_id"])
    existing = (
        await db.execute(
            select(ResultItem).where(
                ResultItem.result_id == result.id,
                ResultItem.item_id == item_id,
            )
        )
    ).scalar_one_or_none()
    detail = _item_detail(row)
    passed_val = _passed_value(row)
    if existing is None:
        existing = ResultItem(
            result_id=result.id,
            item_id=item_id,
            passed=passed_val,
            raw_answer=row.get("raw_answer"),
            latency_ms=row.get("latency_ms"),
            detail_json=json.dumps(detail) if detail else None,
        )
        db.add(existing)
    else:
        existing.passed = passed_val
        existing.raw_answer = row.get("raw_answer")
        existing.latency_ms = row.get("latency_ms")
        existing.detail_json = json.dumps(detail) if detail else None
    await db.flush()
    if commit:
        await db.commit()
        await db.refresh(result)
    return existing


def _score_from_items(
    items: list[ResultItem],
    *,
    planned_n: int,
    task_name: str,
    extra_metrics: dict[str, Any] | None = None,
) -> tuple[float | None, float | None, float | None, dict[str, Any]]:
    successes = sum(1 for it in items if it.passed is True)
    scorer_errors = 0
    unparseable = 0
    for it in items:
        try:
            detail = json.loads(it.detail_json) if it.detail_json else {}
        except json.JSONDecodeError:
            detail = {}
        if isinstance(detail, dict):
            if detail.get("scorer_error"):
                scorer_errors += 1
            if detail.get("reason") == "unparseable":
                unparseable += 1
    score = proportion_score(successes, planned_n) if planned_n else None
    ci_low, ci_high = (
        wilson_interval(successes, planned_n) if planned_n else (None, None)
    )
    warn = bool(planned_n and (unparseable / planned_n) > 0.20)
    if (
        task_name.startswith("coding:")
        and score is not None
        and score >= 100.0
        and planned_n >= 40
    ):
        logger.warning(
            "Coding canary: %s scored %.1f on planned_n=%d (LiveCodeBench 100 "
            "on full Standard is treated as impossible)",
            task_name,
            score,
            planned_n,
        )
    metrics = {
        "successes": successes,
        "n": planned_n,
        "planned_n": planned_n,
        "scored_n": planned_n,
        "unparseable": unparseable,
        "scorer_errors": scorer_errors,
        "unparseable_warning": warn,
        "checkpoint": False,
        **(extra_metrics or {}),
    }
    return score, ci_low, ci_high, metrics


async def finalize_axis_result(
    db: AsyncSession,
    result: Result,
    *,
    metrics: dict[str, Any] | None = None,
) -> Result:
    """Recompute aggregate score from all checkpointed items."""
    from sqlalchemy import select

    items = list(
        (
            await db.execute(
                select(ResultItem).where(ResultItem.result_id == result.id)
            )
        ).scalars().all()
    )
    planned_n = int(_metrics_dict(result).get("planned_n") or result.n_items or len(items))
    # Merge caller metrics over checkpoint metrics but keep score fields authoritative.
    prior = _metrics_dict(result)
    extra = {k: v for k, v in prior.items() if k not in {
        "successes", "n", "planned_n", "scored_n", "unparseable",
        "scorer_errors", "unparseable_warning", "checkpoint",
    }}
    if metrics:
        extra.update(metrics)
    score, ci_low, ci_high, m = _score_from_items(
        items, planned_n=planned_n, task_name=result.task_name, extra_metrics=extra
    )
    result.score = score
    result.ci_low = ci_low
    result.ci_high = ci_high
    result.n_items = planned_n
    result.metrics_json = json.dumps(m)
    await db.flush()

    from benchbase.run_log import RunLogManager, run_log_context

    rid = run_log_context.get()
    if rid is not None and score is not None:
        if ci_low is not None and ci_high is not None:
            RunLogManager.log(
                rid,
                f"Persisted {result.task_name}: score={score:.1f} n={planned_n} "
                f"CI=[{ci_low:.1f},{ci_high:.1f}]",
            )
        else:
            RunLogManager.log(
                rid, f"Persisted {result.task_name}: score={score:.1f} n={planned_n}"
            )
    return result


def is_infra_error(exc: BaseException) -> bool:
    """True for LiteLLM/transport failures that should pause, not score as fails."""
    import httpx

    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code if exc.response is not None else 0
        return code in {408, 425, 429, 500, 502, 503, 504}
    text = str(exc).lower()
    needles = (
        "connection refused",
        "connect error",
        "timed out",
        "timeout",
        "name or service not known",
        "temporary failure",
        "502",
        "503",
        "504",
        "bad gateway",
        "service unavailable",
    )
    return any(n in text for n in needles)


async def bump_active_ms(db: AsyncSession, run: Run, delta_ms: float | None) -> None:
    """Accumulate active work time on the run metadata."""
    if not delta_ms or delta_ms <= 0:
        return
    from benchbase.runners.run_metadata import parse_run_metadata

    meta = parse_run_metadata(run)
    meta["active_ms"] = float(meta.get("active_ms") or 0.0) + float(delta_ms)
    run.metadata_json = json.dumps(meta)
    await db.flush()


QualityOutcome = str  # "completed" | "paused" | "cancelled"


async def run_quality_items(
    db: AsyncSession,
    run: Run,
    task_name: str,
    items: list[dict[str, Any]],
    score_one: Any,
    *,
    primary_method: str = "raw",
    metrics: dict[str, Any] | None = None,
    title: str | None = None,
    sample_text_fn: Any = None,
    infra_pause_after: int = 2,
) -> tuple[QualityOutcome, Result]:
    """Resumable quality loop: checkpoint each item; pause on request or infra.

    score_one(item) -> row dict. May raise; infra errors trigger auto-pause.
    """
    from benchbase.run_controller import (
        is_cancelled,
        is_pause_requested,
        request_pause,
    )
    from benchbase.runners.progress_log import AxisProgressLog
    from benchbase.run_log import RunLogManager, run_log_context

    planned_n = len(items)
    result = await ensure_axis_result(
        db,
        run,
        task_name,
        planned_n=planned_n,
        primary_method=primary_method,
        metrics=metrics,
    )
    done_ids = await load_completed_item_ids(db, result)
    progress = AxisProgressLog(
        title=title or task_name,
        total=planned_n,
        tier=run_tier(run).value,
        already_done=len(done_ids),
    )
    consecutive_infra = 0
    rid = run_log_context.get()

    for item in items:
        item_id = str(item.get("item_id", ""))
        if item_id in done_ids:
            continue
        if is_cancelled(run.id):
            if rid is not None:
                RunLogManager.log(rid, "Pause/cancel: stopping before next item.")
            return "cancelled", result
        if is_pause_requested(run.id):
            if rid is not None:
                RunLogManager.log(
                    rid,
                    f"Paused after {len(done_ids)}/{planned_n} items (progress kept).",
                )
            return "paused", result

        try:
            row = await score_one(item)
            if not isinstance(row, dict):
                raise TypeError("score_one must return a dict row")
            row.setdefault("item_id", item_id)
            consecutive_infra = 0
        except Exception as exc:
            if is_infra_error(exc):
                consecutive_infra += 1
                if rid is not None:
                    RunLogManager.log(
                        rid,
                        f"Infra error on {item_id} "
                        f"({consecutive_infra}/{infra_pause_after}): {exc}",
                    )
                if consecutive_infra >= infra_pause_after:
                    request_pause(run.id)
                    if rid is not None:
                        RunLogManager.log(
                            rid,
                            "Auto-paused: LiteLLM/transport unavailable. "
                            "Resume when ready.",
                        )
                    return "paused", result
                # Brief backoff then retry the same item once more.
                import asyncio

                await asyncio.sleep(1.0)
                try:
                    row = await score_one(item)
                    if not isinstance(row, dict):
                        raise TypeError("score_one must return a dict row")
                    row.setdefault("item_id", item_id)
                    consecutive_infra = 0
                except Exception as exc2:
                    if is_infra_error(exc2):
                        request_pause(run.id)
                        if rid is not None:
                            RunLogManager.log(
                                rid,
                                f"Infra error retry failed on {item_id}: {exc2}",
                            )
                            RunLogManager.log(
                                rid,
                                "Auto-paused: LiteLLM/transport unavailable. "
                                "Resume when ready.",
                            )
                        return "paused", result
                    row = {
                        "item_id": item_id,
                        "passed": None,
                        "raw_answer": str(exc2)[:500],
                        "scorer_error": True,
                        "reason": "scorer-error",
                    }
                    consecutive_infra = 0
            else:
                row = {
                    "item_id": item_id,
                    "passed": None,
                    "raw_answer": str(exc)[:500],
                    "scorer_error": True,
                    "reason": "scorer-error",
                }
                consecutive_infra = 0

        await checkpoint_item(db, result, row, commit=True)
        done_ids.add(item_id)
        sample = None
        if sample_text_fn is not None:
            try:
                sample = sample_text_fn(item, row)
            except Exception:
                sample = None
        progress.record(row, sample_text=sample)

        if is_cancelled(run.id):
            return "cancelled", result
        if is_pause_requested(run.id):
            if rid is not None:
                RunLogManager.log(
                    rid,
                    f"Paused after {len(done_ids)}/{planned_n} items (progress kept).",
                )
            return "paused", result

    await finalize_axis_result(db, result, metrics=metrics)
    await db.commit()
    progress.finish(result.score)
    return "completed", result


def run_tier(run: Run) -> RunTier:
    return run.tier if isinstance(run.tier, RunTier) else RunTier.STANDARD


def suite_version_for_run(run: Run) -> str:
    if run.suite and run.suite.suite_version:
        return run.suite.suite_version
    return DEFAULT_SUITE_VERSION
