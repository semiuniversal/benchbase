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

    async def vision_support_map(self, model_ids: list[str] | None = None) -> dict[str, bool]:
        """Return {model_id: supports_vision} from LiteLLM metadata when available."""
        info = await self.model_info_map(model_ids)
        return {mid: bool(row.get("supports_vision")) for mid, row in info.items()}

    async def model_info_map(
        self, model_ids: list[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """Return {model_id: {supports_vision, context_window, max_output_tokens, raw}}."""
        out: dict[str, dict[str, Any]] = {}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/model/info", headers=self._headers()
                )
                if resp.status_code == 200:
                    payload = resp.json()
                    rows = payload.get("data") or payload.get("models") or []
                    if isinstance(rows, dict):
                        rows = list(rows.values())
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        mid = (
                            row.get("model_name")
                            or row.get("id")
                            or row.get("model_id")
                            or ""
                        )
                        if not mid:
                            continue
                        info = row.get("model_info") or row.get("info") or row
                        if not isinstance(info, dict):
                            info = row
                        out[str(mid)] = self._extract_model_info(info, row)
        except Exception as exc:
            logger.debug("LiteLLM /model/info probe failed: %s", exc)

        try:
            for m in await self.list_models():
                mid = m.get("id") or ""
                if not mid or mid in out:
                    continue
                out[mid] = self._extract_model_info(m, m)
        except Exception as exc:
            logger.debug("LiteLLM /v1/models info probe failed: %s", exc)

        if model_ids:
            return {
                mid: out.get(mid)
                or next(
                    (v for k, v in out.items() if k.lower() == mid.lower()),
                    {
                        "supports_vision": False,
                        "context_window": None,
                        "max_output_tokens": None,
                        "raw": {},
                    },
                )
                for mid in model_ids
            }
        return out

    @classmethod
    def _extract_model_info(
        cls, info: dict[str, Any], row: dict[str, Any]
    ) -> dict[str, Any]:
        supports_vision = cls._extract_supports_vision(info) or cls._extract_supports_vision(row)
        context = cls._first_int(
            info,
            row,
            keys=(
                "max_input_tokens",
                "max_tokens",
                "context_window",
                "max_seq_len",
                "model_max_input_tokens",
            ),
        )
        max_out = cls._first_int(
            info,
            row,
            keys=(
                "max_output_tokens",
                "max_completion_tokens",
                "model_max_output_tokens",
            ),
        )
        # Compact raw snapshot — keep useful published keys only.
        raw_keys = (
            "supports_vision",
            "supports_function_calling",
            "supports_tool_choice",
            "mode",
            "litellm_provider",
            "max_input_tokens",
            "max_output_tokens",
            "max_tokens",
            "context_window",
        )
        raw: dict[str, Any] = {}
        for src in (info, row):
            if not isinstance(src, dict):
                continue
            for k in raw_keys:
                if k in src and src[k] is not None and k not in raw:
                    raw[k] = src[k]
        return {
            "supports_vision": supports_vision,
            "context_window": context,
            "max_output_tokens": max_out,
            "raw": raw,
        }

    @staticmethod
    def _first_int(
        *dicts: dict[str, Any], keys: tuple[str, ...]
    ) -> int | None:
        for d in dicts:
            if not isinstance(d, dict):
                continue
            for k in keys:
                v = d.get(k)
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)) and v > 0:
                    return int(v)
                if isinstance(v, str) and v.isdigit():
                    return int(v)
        return None

    @staticmethod
    def _extract_supports_vision(data: dict[str, Any] | None) -> bool:
        if not data or not isinstance(data, dict):
            return False
        if data.get("supports_vision") is True:
            return True
        info = data.get("model_info")
        if isinstance(info, dict) and info.get("supports_vision") is True:
            return True
        modalities = data.get("modalities") or data.get("supported_modalities")
        if isinstance(modalities, dict):
            input_mods = modalities.get("input") or modalities.get("inputs") or []
            if isinstance(input_mods, list) and any(
                str(x).lower() in ("image", "vision") for x in input_mods
            ):
                return True
        if isinstance(modalities, list) and any(
            str(x).lower() in ("image", "vision") for x in modalities
        ):
            return True
        mode = str(data.get("mode") or "").lower()
        if mode in ("vision", "image"):
            return True
        return False

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
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        async with httpx.AsyncClient(timeout=300) as client:
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
        messages: list[dict[str, Any]],
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
