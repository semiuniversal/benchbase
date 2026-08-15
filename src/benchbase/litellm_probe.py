"""Probe LiteLLM for sticky generation params that poison quality benchmarks.

Quality axes send small max_tokens budgets. If LiteLLM injects a large
min_tokens (e.g. 2048) via extra_body, every call becomes a forced dump and
work-clock / accuracy comparisons lie. Speed warmup with max_tokens=1 fails
with HTTP 400 when min_tokens is sticky — same signal we use here.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from benchbase.litellm_client import LiteLLMClient

_STICKY_MIN_TOKENS_RE = re.compile(
    r"min_tokens\s+must\s+be\s+<=\s*max_tokens\s*=\s*(\d+)",
    re.IGNORECASE,
)
_ANY_MIN_TOKENS_RE = re.compile(r"min_tokens", re.IGNORECASE)


async def probe_sticky_min_tokens(
    client: LiteLLMClient,
    model: str,
    *,
    timeout: float = 30,
) -> dict[str, Any]:
    """Return {ok, sticky_min_tokens, detail, model}.

    ok=True when max_tokens=1 completes without a min_tokens constraint error.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single letter A."}],
        "max_tokens": 1,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.post(
                f"{client.base_url}/v1/chat/completions",
                json=payload,
                headers=client._headers(),
            )
    except httpx.TimeoutException:
        return {
            "ok": False,
            "sticky_min_tokens": False,
            "detail": f"timed out after {timeout:.0f}s",
            "model": model,
        }
    except Exception as exc:
        return {
            "ok": False,
            "sticky_min_tokens": False,
            "detail": str(exc),
            "model": model,
        }

    body = resp.text[:500]
    if resp.status_code == 400:
        sticky = bool(_STICKY_MIN_TOKENS_RE.search(body) or _ANY_MIN_TOKENS_RE.search(body))
        if sticky:
            return {
                "ok": False,
                "sticky_min_tokens": True,
                "detail": body.strip(),
                "model": model,
            }
        return {
            "ok": False,
            "sticky_min_tokens": False,
            "detail": f"HTTP 400: {body.strip()}",
            "model": model,
        }

    if resp.status_code != 200:
        return {
            "ok": False,
            "sticky_min_tokens": False,
            "detail": f"HTTP {resp.status_code}: {body.strip()}",
            "model": model,
        }

    try:
        data = resp.json()
    except Exception as exc:
        return {
            "ok": False,
            "sticky_min_tokens": False,
            "detail": f"invalid JSON: {exc}",
            "model": model,
        }

    if not LiteLLMClient._response_has_output(data):
        return {
            "ok": False,
            "sticky_min_tokens": False,
            "detail": "HTTP 200 but empty completion",
            "model": model,
        }

    usage = data.get("usage") or {}
    completion_tokens = usage.get("completion_tokens")
    if isinstance(completion_tokens, (int, float)) and completion_tokens > 8:
        return {
            "ok": False,
            "sticky_min_tokens": True,
            "detail": (
                f"max_tokens=1 probe returned {int(completion_tokens)} completion tokens "
                "(likely sticky min_tokens or ignore_eos on quality route)"
            ),
            "model": model,
        }

    return {
        "ok": True,
        "sticky_min_tokens": False,
        "detail": "quality route accepts max_tokens=1 (no sticky min_tokens)",
        "model": model,
    }


async def probe_litellm_quality_route(
    client: LiteLLMClient | None = None,
    *,
    model: str | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    """Probe proxy quality route; pick model from arg or first listed model."""
    client = client or LiteLLMClient()
    probe_model = model
    if not probe_model:
        models = await client.list_models()
        if not models:
            return {
                "ok": False,
                "sticky_min_tokens": False,
                "detail": "LiteLLM returned no models",
                "model": None,
            }
        probe_model = str(models[0].get("id") or "")
    if not probe_model:
        return {
            "ok": False,
            "sticky_min_tokens": False,
            "detail": "No model id to probe",
            "model": None,
        }
    result = await probe_sticky_min_tokens(client, probe_model, timeout=timeout)
    result["base_url"] = client.base_url
    return result
