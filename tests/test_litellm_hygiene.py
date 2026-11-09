"""LiteLLM restart / sticky hygiene helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from benchbase.litellm_hygiene import restart_litellm


@pytest.mark.asyncio
async def test_restart_via_docker_sock_when_available():
    probe = {
        "ok": True,
        "sticky_min_tokens": False,
        "detail": "clean",
        "model": "primary",
    }
    with (
        patch("benchbase.litellm_hygiene.docker_sock_available", return_value=True),
        patch(
            "benchbase.litellm_hygiene._docker_restart_sock",
            new_callable=AsyncMock,
        ) as restart,
        patch(
            "benchbase.litellm_hygiene.wait_litellm_ready",
            new_callable=AsyncMock,
        ) as wait,
        patch(
            "benchbase.litellm_hygiene.probe_litellm_quality_route",
            new_callable=AsyncMock,
            return_value=probe,
        ),
    ):
        out = await restart_litellm()
    restart.assert_awaited()
    wait.assert_awaited()
    assert out["method"] == "docker_api"
    assert out["ok"] is True
    assert out["sticky_min_tokens"] is False


@pytest.mark.asyncio
async def test_restart_via_docker_cli_when_no_sock():
    probe = {
        "ok": True,
        "sticky_min_tokens": False,
        "detail": "clean",
        "model": "primary",
    }
    with (
        patch("benchbase.litellm_hygiene.docker_sock_available", return_value=False),
        patch("benchbase.litellm_hygiene.docker_cli_available", return_value=True),
        patch("benchbase.litellm_hygiene._docker_restart_cli") as restart,
        patch(
            "benchbase.litellm_hygiene.wait_litellm_ready",
            new_callable=AsyncMock,
        ),
        patch(
            "benchbase.litellm_hygiene.probe_litellm_quality_route",
            new_callable=AsyncMock,
            return_value=probe,
        ),
    ):
        out = await restart_litellm()
    restart.assert_called_once_with("litellm")
    assert out["method"] == "docker"


@pytest.mark.asyncio
async def test_restart_via_model_roles_when_no_docker():
    probe = {
        "ok": True,
        "sticky_min_tokens": False,
        "detail": "clean",
        "model": "seat-a",
    }
    hygiene = {"job_id": "j1", "job": {"state": "SUCCEEDED"}, "restarted": True}

    with (
        patch("benchbase.litellm_hygiene.docker_sock_available", return_value=False),
        patch("benchbase.litellm_hygiene.docker_cli_available", return_value=False),
        patch(
            "benchbase.litellm_hygiene._hygiene_via_model_roles",
            new_callable=AsyncMock,
            return_value=hygiene,
        ) as roles,
        patch(
            "benchbase.litellm_hygiene.wait_litellm_ready",
            new_callable=AsyncMock,
        ),
        patch(
            "benchbase.litellm_hygiene.probe_litellm_quality_route",
            new_callable=AsyncMock,
            return_value=probe,
        ),
    ):
        out = await restart_litellm(scope="primary")
    roles.assert_awaited()
    assert out["method"] == "model_roles"
    assert out["ok"] is True
    assert out["detail"]["hygiene"]["job_id"] == "j1"


@pytest.mark.asyncio
async def test_restart_reports_sticky_after_probe():
    probe = {
        "ok": False,
        "sticky_min_tokens": True,
        "detail": "min_tokens must be <= max_tokens=1",
        "model": "x",
    }
    with (
        patch("benchbase.litellm_hygiene.docker_sock_available", return_value=True),
        patch("benchbase.litellm_hygiene._docker_restart_sock", new_callable=AsyncMock),
        patch("benchbase.litellm_hygiene.wait_litellm_ready", new_callable=AsyncMock),
        patch(
            "benchbase.litellm_hygiene.probe_litellm_quality_route",
            new_callable=AsyncMock,
            return_value=probe,
        ),
    ):
        out = await restart_litellm()
    assert out["ok"] is False
    assert out["sticky_min_tokens"] is True
