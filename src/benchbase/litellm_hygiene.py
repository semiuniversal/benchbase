"""Clear sticky LiteLLM generation params (Speed exact-tg residue).

After BenchBase Speed `--exact-tg`, LiteLLM can retain `min_tokens` /
`ignore_eos` on a route in process memory. Restarting the proxy clears it.

Strategies (first that works):
1. Docker Engine API via `/var/run/docker.sock` (preferred in compose)
2. `docker restart` CLI when available
3. model-roles `POST /v1/proxy/hygiene` with fix=true (lab fallback)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from typing import Any

import httpx

from benchbase.config import load_settings
from benchbase.litellm_probe import probe_litellm_quality_route


DEFAULT_MODEL_ROLES_URL = "http://host.docker.internal:20007"
DEFAULT_CONTAINER = "litellm"
DEFAULT_DOCKER_SOCK = "/var/run/docker.sock"


def _model_roles_base() -> str:
    return (
        os.environ.get("BENCHBASE_MODEL_ROLES_URL")
        or os.environ.get("MODEL_ROLES_URL")
        or DEFAULT_MODEL_ROLES_URL
    ).rstrip("/")


def _container_name() -> str:
    return os.environ.get("BENCHBASE_LITELLM_CONTAINER", DEFAULT_CONTAINER)


def _docker_sock() -> str:
    return os.environ.get("BENCHBASE_DOCKER_SOCK", DEFAULT_DOCKER_SOCK)


def docker_sock_available() -> bool:
    path = _docker_sock()
    return os.path.exists(path) and os.access(path, os.R_OK)


def docker_cli_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def docker_restart_available() -> bool:
    return docker_sock_available() or docker_cli_available()


def _docker_restart_cli(container: str) -> None:
    proc = subprocess.run(
        ["docker", "restart", container],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"docker restart {container} failed: {err[-2000:]}")


async def _docker_restart_sock(container: str) -> None:
    sock = _docker_sock()
    transport = httpx.AsyncHTTPTransport(uds=sock)
    async with httpx.AsyncClient(transport=transport, timeout=120.0) as http:
        resp = await http.post(f"http://localhost/containers/{container}/restart")
        if resp.status_code >= 300:
            raise RuntimeError(
                f"docker API restart {container} failed: "
                f"{resp.status_code} {resp.text[:500]}"
            )


async def wait_litellm_ready(*, timeout: float = 90.0) -> None:
    """Poll LiteLLM until it accepts traffic again."""
    settings = load_settings()
    base = settings.litellm_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    headers: dict[str, str] = {}
    if settings.litellm_api_key:
        headers["Authorization"] = f"Bearer {settings.litellm_api_key}"

    deadline = time.monotonic() + timeout
    last_err = "not started"
    async with httpx.AsyncClient(timeout=3.0) as http:
        while time.monotonic() < deadline:
            for path in ("/health/liveliness", "/health", "/v1/models"):
                try:
                    resp = await http.get(f"{base}{path}", headers=headers)
                    if resp.status_code < 500:
                        return
                    last_err = f"{path} -> {resp.status_code}"
                except Exception as exc:  # noqa: BLE001
                    last_err = str(exc)
            await asyncio.sleep(2)
    raise RuntimeError(f"LiteLLM did not become ready in time ({last_err})")


async def _hygiene_via_model_roles(
    *,
    scope: str,
    base_url: str,
    timeout: float,
) -> dict[str, Any]:
    """Call model-roles hygiene. Restart success matters more than their probe.

    model-roles may mark PROXY_DIRTY on HTTP 401 for `primary` even after a good
    restart; BenchBase re-probes with its own LiteLLM credentials afterward.
    """
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.post(
            f"{base_url}/v1/proxy/hygiene",
            json={"scope": scope, "fix": True},
        )
        resp.raise_for_status()
        handle = resp.json()
        job_id = handle.get("job_id")
        if not job_id:
            raise RuntimeError(f"model-roles hygiene returned no job_id: {handle}")

        deadline = time.monotonic() + timeout
        last: dict[str, Any] = handle
        while time.monotonic() < deadline:
            jr = await http.get(f"{base_url}/v1/jobs/{job_id}")
            jr.raise_for_status()
            last = jr.json()
            state = last.get("state")
            if state == "SUCCEEDED":
                return {"job_id": job_id, "job": last, "restarted": True}
            if state == "FAILED":
                result = last.get("result") or {}
                if result.get("restarted"):
                    # Proxy was restarted; ignore their post-probe auth noise.
                    return {
                        "job_id": job_id,
                        "job": last,
                        "restarted": True,
                        "warning": last.get("error") or "hygiene probe failed after restart",
                    }
                raise RuntimeError(
                    last.get("error") or f"model-roles hygiene failed: {last}"
                )
            await asyncio.sleep(1.5)
        raise RuntimeError(
            f"model-roles hygiene timed out (job_id={job_id}, last={last.get('state')})"
        )


async def restart_litellm(
    *,
    scope: str = "primary",
    probe_model: str | None = None,
    wait_timeout: float = 90.0,
) -> dict[str, Any]:
    """Restart LiteLLM to clear sticky Speed params; then probe the quality route."""
    method: str
    detail: dict[str, Any] = {}
    container = _container_name()

    if docker_sock_available():
        await _docker_restart_sock(container)
        method = "docker_api"
        detail["container"] = container
        detail["docker_sock"] = _docker_sock()
        await wait_litellm_ready(timeout=wait_timeout)
    elif docker_cli_available():
        await asyncio.to_thread(_docker_restart_cli, container)
        method = "docker"
        detail["container"] = container
        await wait_litellm_ready(timeout=wait_timeout)
    else:
        roles_base = _model_roles_base()
        detail["model_roles_url"] = roles_base
        hygiene = await _hygiene_via_model_roles(
            scope=scope,
            base_url=roles_base,
            timeout=wait_timeout,
        )
        method = "model_roles"
        detail["hygiene"] = hygiene
        await wait_litellm_ready(timeout=min(45.0, wait_timeout))

    probe = await probe_litellm_quality_route(model=probe_model)
    sticky = bool(probe.get("sticky_min_tokens"))
    # Contamination cleared iff not sticky. Auth/probe noise on an unrelated
    # alias (e.g. primary → upstream key) must not fail the restart action.
    return {
        "ok": not sticky,
        "restarted": True,
        "method": method,
        "detail": detail,
        "probe": probe,
        "sticky_min_tokens": sticky,
    }
