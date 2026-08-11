"""OpenRouter client for instrument roles (simulator / judge / harness proof).

Local deployments under evaluation must never fill these roles.
Default model: deepseek/deepseek-v4-flash-0731 via OpenRouter's OpenAI-compatible API.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
DEFAULT_INSTRUMENT_MODEL = "deepseek/deepseek-v4-flash-0731"


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatResult:
    content: str
    model: str
    raw: dict[str, Any]


class OpenRouterClient:
    """Minimal chat/completions client. No dependency on local LiteLLM."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.environ.get("OPENROUTER_API_KEY")
            or ""
        ).strip()
        self.base_url = (base_url or os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_OPENROUTER_BASE).rstrip(
            "/"
        )
        self.model = (
            model
            or os.environ.get("OPENROUTER_MODEL")
            or DEFAULT_INSTRUMENT_MODEL
        )
        self.timeout_s = timeout_s

    def require_key(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add it to .env for instrument LLM calls."
            )

    def chat(
        self,
        messages: list[ChatMessage] | list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> ChatResult:
        self.require_key()
        payload_messages: list[dict[str, str]] = []
        for m in messages:
            if isinstance(m, ChatMessage):
                payload_messages.append({"role": m.role, "content": m.content})
            else:
                payload_messages.append(
                    {"role": str(m["role"]), "content": str(m["content"])}
                )
        body = {
            "model": model or self.model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/semiuniversal/benchbase",
                "X-Title": "BenchBase instrument",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {detail}") from exc
        choices = raw.get("choices") or []
        if not choices:
            raise RuntimeError(f"OpenRouter returned no choices: {raw!r}"[:500])
        msg = choices[0].get("message") or {}
        content = str(msg.get("content") or "")
        return ChatResult(content=content, model=str(raw.get("model") or body["model"]), raw=raw)


class UserSimulator:
    """Phase C stub: goal-card interlocutor (stimulus only; never a judge)."""

    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self.client = client or OpenRouterClient()

    def next_user_utterance(
        self,
        *,
        card_summary: str,
        transcript: list[dict[str, str]],
        release_hint: str,
    ) -> str:
        system = (
            "You are a user simulator for agent evaluation. "
            "Release information only per the release hint. "
            "Never hint solutions. Never judge the agent. "
            "Stay in character. Reply with one short user message only."
        )
        user = (
            f"Card summary:\n{card_summary}\n\n"
            f"Release hint:\n{release_hint}\n\n"
            f"Transcript so far (JSON):\n{json.dumps(transcript)}\n"
        )
        result = self.client.chat(
            [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ],
            temperature=0.0,
            max_tokens=256,
        )
        return result.content.strip()


class BinarizedJudge:
    """Phase C stub: Y/N rubric items only. Scores never enter T_eff."""

    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self.client = client or OpenRouterClient()

    def judge_item(self, *, rubric_item: str, transcript_excerpt: str) -> bool:
        system = (
            "You are a binary evaluator. Answer with exactly YES or NO. "
            "No explanation. No other text."
        )
        user = f"Rubric (Y/N):\n{rubric_item}\n\nTranscript excerpt:\n{transcript_excerpt}\n"
        result = self.client.chat(
            [
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=user),
            ],
            temperature=0.0,
            max_tokens=8,
        )
        text = result.content.strip().upper()
        if text.startswith("YES"):
            return True
        if text.startswith("NO"):
            return False
        # Fail closed for ambiguous output
        return False
