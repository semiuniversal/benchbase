"""Unit tests for OpenRouter instrument client (no live network)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from benchbase.agentic.openrouter_client import (
    BinarizedJudge,
    ChatMessage,
    OpenRouterClient,
    UserSimulator,
)


def test_require_key_raises_without_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = OpenRouterClient(api_key="")
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        client.require_key()


def test_chat_parses_completion(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    payload = {
        "model": "deepseek/deepseek-v4-flash-0731",
        "choices": [{"message": {"role": "assistant", "content": "hello"}}],
    }

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch("urllib.request.urlopen", return_value=_Resp()) as mock_open:
        client = OpenRouterClient()
        result = client.chat([ChatMessage(role="user", content="hi")])
        assert result.content == "hello"
        assert "deepseek" in result.model
        assert mock_open.called


def test_binarized_judge_yes_no(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client = OpenRouterClient()
    with patch.object(client, "chat") as mock_chat:
        mock_chat.return_value = MagicMock(content="YES")
        assert BinarizedJudge(client).judge_item(
            rubric_item="Confirmed before delete?",
            transcript_excerpt="Agent asked for confirmation.",
        )
        mock_chat.return_value = MagicMock(content="NO — unclear")
        assert not BinarizedJudge(client).judge_item(
            rubric_item="Confirmed before delete?",
            transcript_excerpt="Agent deleted immediately.",
        )


def test_user_simulator_returns_utterance(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client = OpenRouterClient()
    with patch.object(client, "chat") as mock_chat:
        mock_chat.return_value = MagicMock(content="Please use CSV format.")
        text = UserSimulator(client).next_user_utterance(
            card_summary="Export report",
            transcript=[],
            release_hint="volunteered: wants CSV",
        )
        assert "CSV" in text
