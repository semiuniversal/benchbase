"""Shared helpers for v2 quality-axis runners (extract-then-compare)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Result, ResultItem, Run, RunTier
from benchbase.litellm_client import LiteLLMClient
from benchbase.stats import proportion_score, wilson_interval

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
        "max_tokens": max_tokens,
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
        content = msg.get("content") or msg.get("reasoning_content") or ""
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
    scorer_error?  scorer_error items are excluded from the proportion.
    """
    scored = [r for r in item_rows if not r.get("scorer_error")]
    n = len(scored)
    successes = sum(1 for r in scored if r.get("passed"))
    score = proportion_score(successes, n) if n else None
    ci_low, ci_high = wilson_interval(successes, n) if n else (None, None)
    unparseable = sum(1 for r in item_rows if r.get("reason") == "unparseable")
    scorer_errors = sum(1 for r in item_rows if r.get("scorer_error"))
    warn = bool(n and (unparseable / max(len(item_rows), 1)) > 0.20)
    result = Result(
        run_id=run.id,
        task_name=task_name,
        score=score,
        ci_low=ci_low,
        ci_high=ci_high,
        n_items=n,
        primary_method=primary_method,
        metrics_json=json.dumps(
            {
                "successes": successes,
                "n": n,
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
                f"Persisted {task_name}: score={score:.1f} n={n} "
                f"CI=[{ci_low:.1f},{ci_high:.1f}]",
            )
        else:
            RunLogManager.log(rid, f"Persisted {task_name}: score={score:.1f} n={n}")
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
        if row.get("scorer_error"):
            detail["scorer_error"] = True
        db.add(
            ResultItem(
                result_id=result.id,
                item_id=str(row["item_id"]),
                passed=bool(row.get("passed")) if row.get("passed") is not None else None,
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
