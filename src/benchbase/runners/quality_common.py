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
    """Persist aggregate + per-item rows.

    item_rows: item_id, passed, raw_answer?, latency_ms?, reason?, detail?,
    scorer_error?  scorer_error is treated like harness_error: fail, kept in
    the denominator (planned_n).
    """
    planned_n = len(item_rows)
    scorer_errors = sum(1 for r in item_rows if r.get("scorer_error"))
    successes = 0
    for r in item_rows:
        if r.get("scorer_error"):
            continue
        if r.get("passed") is True:
            successes += 1
    scored_n = planned_n
    score = proportion_score(successes, planned_n) if planned_n else None
    ci_low, ci_high = (
        wilson_interval(successes, planned_n) if planned_n else (None, None)
    )
    unparseable = sum(1 for r in item_rows if r.get("reason") == "unparseable")
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
    result = Result(
        run_id=run.id,
        task_name=task_name,
        score=score,
        ci_low=ci_low,
        ci_high=ci_high,
        n_items=planned_n,
        primary_method=primary_method,
        metrics_json=json.dumps(
            {
                "successes": successes,
                "n": planned_n,
                "planned_n": planned_n,
                "scored_n": scored_n,
                "unparseable": unparseable,
                "scorer_errors": scorer_errors,
                "unparseable_warning": warn,
                **(metrics or {}),
            }
        ),
    )
    db.add(result)
    await db.flush()
    from benchbase.run_log import RunLogManager, run_log_context

    rid = run_log_context.get()
    if rid is not None and score is not None:
        if ci_low is not None and ci_high is not None:
            RunLogManager.log(
                rid,
                f"Persisted {task_name}: score={score:.1f} n={planned_n} "
                f"CI=[{ci_low:.1f},{ci_high:.1f}]",
            )
        else:
            RunLogManager.log(
                rid, f"Persisted {task_name}: score={score:.1f} n={planned_n}"
            )
    for row in item_rows:
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
        scorer_err = bool(row.get("scorer_error"))
        if scorer_err:
            detail["scorer_error"] = True
        if scorer_err:
            passed_val: bool | None = False
        elif row.get("passed") is not None:
            passed_val = bool(row.get("passed"))
        else:
            passed_val = None
        db.add(
            ResultItem(
                result_id=result.id,
                item_id=str(row["item_id"]),
                passed=passed_val,
                raw_answer=row.get("raw_answer"),
                latency_ms=row.get("latency_ms"),
                detail_json=json.dumps(detail) if detail else None,
            )
        )
    await db.flush()
    return result


def run_tier(run: Run) -> RunTier:
    return run.tier if isinstance(run.tier, RunTier) else RunTier.STANDARD


def suite_version_for_run(run: Run) -> str:
    if run.suite and run.suite.suite_version:
        return run.suite.suite_version
    return DEFAULT_SUITE_VERSION
