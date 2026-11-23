"""Verify LLManifold route shape for BenchBase Speed (--exact-tg).

Contract: the OpenAI `model` id Speed sends must be a route whose `allow` list
includes both `min_tokens` and `ignore_eos`. Otherwise the gateway strips forcing
keys and decode tok/s stays gated. See doc/vnext/SPEED_DECODE_ROUTE_PROCEDURE.md.
"""

from __future__ import annotations

from typing import Any

import httpx

from benchbase.config import inference_server_origin, load_settings

REQUIRED_ALLOW = frozenset({"min_tokens", "ignore_eos"})
PROCEDURE_DOC = "doc/vnext/SPEED_DECODE_ROUTE_PROCEDURE.md"


def _parse_routes_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        routes = payload.get("routes")
        if isinstance(routes, list):
            return [r for r in routes if isinstance(r, dict)]
        if isinstance(routes, dict):
            return list(routes.values())
    return []


def assess_route_card(route: dict[str, Any] | None, model_name: str) -> dict[str, Any]:
    """Return {ok, model, allow, clients, reason, fix_hint}."""
    base = {"model": model_name, "allow": [], "clients": []}
    if route is None:
        return {
            **base,
            "ok": False,
            "reason": "route_not_listed",
            "fix_hint": (
                f'No LLManifold route named "{model_name}". Publish one with '
                "clients: [benchbase] and allow: [min_tokens, ignore_eos], or rename "
                "the bench route to match BenchBase Model.name."
            ),
        }
    allow = {str(x) for x in route.get("allow") or []}
    clients = [str(x) for x in route.get("clients") or []]
    base["allow"] = sorted(allow)
    base["clients"] = clients
    if REQUIRED_ALLOW.issubset(allow):
        return {**base, "ok": True, "reason": None, "fix_hint": None}
    if "benchbase" in clients and len(clients) > 1:
        fix = (
            f'Route "{model_name}" lists benchbase with other consumers but allow is empty — '
            "exact-tg is stripped. Split: chat route without benchbase; bench route with "
            "allow: [min_tokens, ignore_eos] and name == BenchBase Model.name."
        )
        return {**base, "ok": False, "reason": "shared_route_strips_forcing", "fix_hint": fix}
    if clients == ["benchbase"] or clients == ["benchbase",]:
        fix = (
            f'Route "{model_name}" is benchbase-only but missing allow keys. '
            "update_route allow: [min_tokens, ignore_eos]."
        )
        return {**base, "ok": False, "reason": "bench_only_missing_allow", "fix_hint": fix}
    fix = (
        f'Route "{model_name}" does not allow min_tokens/ignore_eos. '
        "Speed will not get comparable decode tok/s."
    )
    return {**base, "ok": False, "reason": "allow_missing", "fix_hint": fix}


async def fetch_manifold_route(
    route_name: str,
    *,
    timeout: float = 15,
    origin: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    settings = load_settings()
    root = origin or inference_server_origin(settings.litellm_base_url)
    url = f"{root}/api/routes"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        return None, f"could not reach LLManifold at {url}: {exc}"
    if resp.status_code != 200:
        return None, f"GET {url} returned HTTP {resp.status_code}"
    try:
        data = resp.json()
    except ValueError:
        return None, f"GET {url} did not return JSON"
    for route in _parse_routes_list(data):
        if route.get("name") == route_name:
            return route, None
    return None, None


async def verify_benchbase_speed_route(
    model_name: str,
    *,
    timeout: float = 15,
    origin: str | None = None,
) -> dict[str, Any]:
    """Check LLManifold route card for a BenchBase Speed run."""
    route, fetch_error = await fetch_manifold_route(model_name, timeout=timeout, origin=origin)
    if fetch_error:
        return {
            "model": model_name,
            "ok": False,
            "reason": "manifold_unreachable",
            "fix_hint": fetch_error,
            "allow": [],
            "clients": [],
            "procedure": PROCEDURE_DOC,
        }
    out = assess_route_card(route, model_name)
    out["procedure"] = PROCEDURE_DOC
    return out


async def verify_active_model_routes(
    model_names: list[str],
    *,
    timeout: float = 15,
) -> dict[str, Any]:
    """Batch verify; returns {results: [...], failing: n}."""
    results = []
    for name in model_names:
        results.append(await verify_benchbase_speed_route(name, timeout=timeout))
    failing = sum(1 for r in results if not r.get("ok"))
    return {"results": results, "failing": failing, "procedure": PROCEDURE_DOC}