"""Async client for OpenAI-compatible endpoints (e.g. LiteLLM proxy)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import httpx

from benchbase.config import load_settings

logger = logging.getLogger(__name__)


class LiteLLMClient:
    """Thin wrapper around an OpenAI-compatible HTTP API."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        settings = load_settings()
        self.base_url = (base_url or settings.litellm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.litellm_api_key

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    _EMBEDDING_INDICATORS = {"embed", "e5", "bge", "gte", "nomic-embed", "text-embedding"}

    async def list_models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/v1/models", headers=self._headers()
            )
            resp.raise_for_status()
            all_models = resp.json().get("data", [])
            return [m for m in all_models if not self._is_embedding_model(m)]

    @classmethod
    def _is_embedding_model(cls, model: dict[str, Any]) -> bool:
        """Heuristic: skip models that look like embedding/reranker models."""
        model_id = (model.get("id") or "").lower()
        object_type = (model.get("object") or "").lower()
        if object_type == "embedding":
            return True
        return any(tag in model_id for tag in cls._EMBEDDING_INDICATORS)

    async def ping_model(self, model: str, timeout: float = 60) -> bool:
        """Send a minimal chat completion; proves the model can respond."""
        ok, _ = await self.ping_model_detailed(model, timeout=timeout)
        return ok

    async def ping_model_detailed(
        self, model: str, timeout: float = 60
    ) -> tuple[bool, str]:
        """Like ping_model but returns (ok, failure_detail) for UI and logs."""
        ok, detail = await self._ping_once(model, timeout=min(timeout, 30))
        if ok:
            return True, ""
        await asyncio.sleep(10)
        ok, detail = await self._ping_once(model, timeout=max(timeout, 120))
        return ok, detail if not ok else ""

    async def ping_model_health(
        self, model: str, timeout: float = 15
    ) -> tuple[bool, str]:
        """Fast health ping for bulk recheck — no long retry loop."""
        ok, detail = await self._ping_once(model, timeout=timeout)
        if ok:
            return True, ""
        # Retry once only on timeouts; HTTP errors fail immediately.
        if "timed out" in detail.lower():
            await asyncio.sleep(2)
            return await self._ping_once(model, timeout=timeout)
        return False, detail

    async def _ping_once(self, model: str, timeout: float) -> tuple[bool, str]:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 4,
            "temperature": 0,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    detail = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.info("Health check for %s failed: %s", model, detail)
                    return False, detail
                if self._response_has_output(resp.json()):
                    return True, ""
                detail = "HTTP 200 but empty completion (no content or reasoning tokens)"
                logger.info("Health check for %s failed: %s", model, detail)
                return False, detail
        except httpx.TimeoutException:
            detail = f"timed out after {timeout:.0f}s"
            logger.info("Health check for %s %s", model, detail)
            return False, detail
        except Exception as exc:
            detail = str(exc)
            logger.info("Health check for %s failed: %s", model, exc)
            return False, detail

    @staticmethod
    def _response_has_output(data: dict[str, Any]) -> bool:
        """True when the API returned a usable completion (incl. reasoning-only models)."""
        choices = data.get("choices") or []
        if not choices:
            return False
        for choice in choices:
            if choice.get("text"):
                return True
            message = choice.get("message") or {}
            for key in ("content", "reasoning_content", "reasoning"):
                value = message.get(key)
                if value is not None and str(value).strip():
                    return True
            # Thinking models may return null content with a finish_reason after tokens.
            if choice.get("finish_reason") in ("stop", "length"):
                usage = data.get("usage") or {}
                if (usage.get("completion_tokens") or 0) > 0:
                    return True
        return False

    async def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def stream_chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield (kind, text) tuples: kind is 'thinking' or 'content'."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    chunk = json.loads(data)
                    choices = chunk.get("choices", [])
                    if choices:
                        delta = choices[0].get("delta", {})
                        reasoning = delta.get("reasoning_content") or ""
                        content = delta.get("content") or ""
                        if reasoning:
                            yield ("thinking", reasoning)
                        if content:
                            yield ("content", content)
