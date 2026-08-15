"""LiteLLM quality-route probe (sticky min_tokens detection)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from benchbase.litellm_client import LiteLLMClient
from benchbase.litellm_probe import probe_litellm_quality_route, probe_sticky_min_tokens


def test_probe_passes_on_max_tokens_one_success():
    client = LiteLLMClient(base_url="http://litellm.test", api_key="k")

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [{"message": {"content": "A"}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 1},
            }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _Resp()
        result = asyncio.run(probe_sticky_min_tokens(client, "seat-a"))
    assert result["ok"] is True
    assert result["sticky_min_tokens"] is False
    payload = mock_post.call_args.kwargs["json"]
    assert payload["max_tokens"] == 1
    assert "min_tokens" not in payload


def test_probe_detects_sticky_min_tokens_400():
    client = LiteLLMClient(base_url="http://litellm.test", api_key="k")

    class _Resp:
        status_code = 400
        text = '{"error":{"message":"min_tokens must be <= max_tokens=1"}}'

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _Resp()
        result = asyncio.run(probe_sticky_min_tokens(client, "seat-a"))
    assert result["ok"] is False
    assert result["sticky_min_tokens"] is True
    assert "min_tokens" in result["detail"]


def test_probe_detects_forced_long_completion():
    client = LiteLLMClient(base_url="http://litellm.test", api_key="k")

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {
                "choices": [{"message": {"content": "x" * 50}, "finish_reason": "length"}],
                "usage": {"completion_tokens": 2048},
            }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = _Resp()
        result = asyncio.run(probe_sticky_min_tokens(client, "seat-a"))
    assert result["ok"] is False
    assert result["sticky_min_tokens"] is True


def test_probe_litellm_picks_first_model():
    client = LiteLLMClient(base_url="http://litellm.test", api_key="k")
    with patch.object(client, "list_models", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [{"id": "first-model"}]
        with patch(
            "benchbase.litellm_probe.probe_sticky_min_tokens",
            new_callable=AsyncMock,
        ) as mock_probe:
            mock_probe.return_value = {
                "ok": True,
                "sticky_min_tokens": False,
                "detail": "ok",
                "model": "first-model",
            }
            result = asyncio.run(probe_litellm_quality_route(client))
    assert result["model"] == "first-model"
    mock_probe.assert_awaited_once_with(client, "first-model", timeout=30)
