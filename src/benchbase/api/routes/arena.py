"""Arena mode – simultaneous multi-model prompting (text + optional vision)."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from benchbase.db.models import Model
from benchbase.db.session import get_db
from benchbase.litellm_client import LiteLLMClient

logger = logging.getLogger(__name__)
router = APIRouter()

VISION_UNSUPPORTED_MSG = "The selected model has no vision support."
ALLOWED_IMAGE_MIME = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 4 * 1024 * 1024
# Vision used to force short completions (512 default / 1024 cap), which truncated
# real answers (finish_reason=length at 512). Match text Arena: no default max_tokens;
# if the client sets one, clamp only to a high safety ceiling.
VISION_MAX_TOKENS_CAP = 16384
VISION_DEFAULT_TEMPERATURE = 0.2


class ArenaImage(BaseModel):
    mime: str = Field(description="image/png|jpeg|webp|gif")
    data_base64: str = Field(description="Raw base64 payload without data: URL prefix.")

    @field_validator("mime")
    @classmethod
    def _mime_ok(cls, v: str) -> str:
        mime = (v or "").lower().strip()
        if mime == "image/jpg":
            mime = "image/jpeg"
        if mime not in ALLOWED_IMAGE_MIME:
            raise ValueError(f"Unsupported image type: {v}")
        return mime

    @field_validator("data_base64")
    @classmethod
    def _size_ok(cls, v: str) -> str:
        raw = (v or "").strip()
        if not raw:
            raise ValueError("Empty image data")
        # Rough size check before decode (base64 expands ~4/3).
        if len(raw) > int(MAX_IMAGE_BYTES * 1.4) + 64:
            raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES} bytes")
        try:
            decoded = base64.b64decode(raw, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Invalid base64 image data") from exc
        if len(decoded) > MAX_IMAGE_BYTES:
            raise ValueError(f"Image exceeds {MAX_IMAGE_BYTES} bytes")
        return raw


class ArenaRequest(BaseModel):
    prompt: str = Field(default="", description="User message sent to each model.")
    models: list[str] = Field(description="LiteLLM model IDs to query in parallel.")
    images: list[ArenaImage] = Field(
        default_factory=list,
        description="Optional images for vision-capable models.",
    )
    max_tokens: int | None = Field(
        default=None,
        description="Maximum completion tokens per model (optional).",
    )
    temperature: float = Field(
        default=0.7,
        description="Sampling temperature for completions.",
    )

    @field_validator("images")
    @classmethod
    def _image_count(cls, v: list[ArenaImage]) -> list[ArenaImage]:
        if len(v) > MAX_IMAGES:
            raise ValueError(f"At most {MAX_IMAGES} images allowed")
        return v


class ArenaChatResponseItem(BaseModel):
    model: str
    content: str | None = None
    error: str | None = None


class ArenaChatResponse(BaseModel):
    responses: list[ArenaChatResponseItem]


def build_user_message(prompt: str, images: list[ArenaImage]) -> dict[str, Any]:
    text = (prompt or "").strip()
    if not images:
        return {"role": "user", "content": text}
    if not text:
        text = "Describe the image(s)."
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for img in images:
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img.mime};base64,{img.data_base64}",
                },
            }
        )
    return {"role": "user", "content": parts}


def resolve_sampling(body: ArenaRequest) -> tuple[int | None, float]:
    """Text-only keeps client settings; vision cools temperature and does not force max_tokens."""
    if not body.images:
        return body.max_tokens, body.temperature
    # Vision: cooler sampling only; do not inject a short max_tokens default.
    max_tokens: int | None = body.max_tokens
    if max_tokens is not None:
        max_tokens = max(1, min(int(max_tokens), VISION_MAX_TOKENS_CAP))
    temperature = min(float(body.temperature), VISION_DEFAULT_TEMPERATURE)
    return max_tokens, temperature


async def _vision_flags(db: AsyncSession, model_names: list[str]) -> dict[str, bool]:
    if not model_names:
        return {}
    result = await db.execute(select(Model).where(Model.name.in_(model_names)))
    return {m.name: bool(m.supports_vision) for m in result.scalars().all()}


@router.post(
    "/chat",
    operation_id="arena_chat",
    summary="Arena chat (non-streaming)",
    description=(
        "Send the same prompt to multiple models and return full responses as JSON. "
        "Use this instead of arena_stream when you need a single structured result."
    ),
    response_model=ArenaChatResponse,
)
async def arena_chat(
    body: ArenaRequest, db: AsyncSession = Depends(get_db)
) -> ArenaChatResponse:
    if not body.models:
        raise HTTPException(400, "Select at least one model")
    if not (body.prompt or "").strip() and not body.images:
        raise HTTPException(400, "Provide a prompt or at least one image")

    client = LiteLLMClient()
    vision = await _vision_flags(db, body.models)
    messages = [build_user_message(body.prompt, body.images)]
    has_images = bool(body.images)
    max_tokens, temperature = resolve_sampling(body)

    async def chat_one(model_name: str) -> ArenaChatResponseItem:
        if has_images and not vision.get(model_name, False):
            return ArenaChatResponseItem(model=model_name, error=VISION_UNSUPPORTED_MSG)
        try:
            result = await client.chat(
                model=model_name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            choices = result.get("choices") or []
            if not choices:
                return ArenaChatResponseItem(model=model_name, error="No choices in response")
            message = choices[0].get("message") or {}
            content = message.get("content")
            if content is None:
                content = message.get("reasoning_content") or message.get("reasoning")
            return ArenaChatResponseItem(
                model=model_name,
                content=str(content) if content is not None else None,
            )
        except Exception as exc:
            logger.error("Arena chat error for model=%s: %s", model_name, exc)
            return ArenaChatResponseItem(model=model_name, error=str(exc))

    results = await asyncio.gather(*(chat_one(m) for m in body.models))
    return ArenaChatResponse(responses=list(results))


@router.post(
    "/stream",
    operation_id="arena_stream",
    summary="Arena stream (SSE)",
    description=(
        "Stream responses from multiple models concurrently via Server-Sent Events. "
        "Not exposed as an MCP tool; use arena_chat for agent integrations."
    ),
)
async def arena_stream(body: ArenaRequest, db: AsyncSession = Depends(get_db)):
    """Stream responses from multiple models concurrently via SSE."""
    if not body.models:
        raise HTTPException(400, "Select at least one model")
    if not (body.prompt or "").strip() and not body.images:
        raise HTTPException(400, "Provide a prompt or at least one image")

    vision = await _vision_flags(db, body.models)
    messages = [build_user_message(body.prompt, body.images)]
    has_images = bool(body.images)
    max_tokens, temperature = resolve_sampling(body)

    async def event_generator():
        client = LiteLLMClient()
        queue: asyncio.Queue = asyncio.Queue()

        async def stream_one(model_name: str):
            if has_images and not vision.get(model_name, False):
                await queue.put(
                    {
                        "model": model_name,
                        "kind": "error",
                        "content": VISION_UNSUPPORTED_MSG,
                        "metrics": None,
                    }
                )
                await queue.put({"_done": model_name})
                return

            logger.info(
                "Arena: starting stream for model=%s max_tokens=%s temperature=%s vision=%s",
                model_name,
                max_tokens,
                temperature,
                has_images,
            )
            start = time.perf_counter()
            first_output_time: float | None = None
            output_chunk_count = 0
            thinking_chunk_count = 0

            try:
                async for kind, chunk in client.stream_chat(
                    model=model_name,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    now = time.perf_counter()
                    if kind == "thinking":
                        thinking_chunk_count += 1
                    elif kind == "content":
                        if first_output_time is None:
                            first_output_time = now - start
                            logger.info(
                                "Arena: first output from model=%s output_ttft=%.3fs",
                                model_name,
                                first_output_time,
                            )
                        output_chunk_count += 1

                    elapsed = now - start
                    output_elapsed = (
                        (now - start) - first_output_time
                        if first_output_time is not None
                        else 0.0
                    )
                    output_tps = (
                        output_chunk_count / output_elapsed
                        if first_output_time is not None and output_elapsed > 0
                        else 0.0
                    )

                    await queue.put(
                        {
                            "model": model_name,
                            "kind": kind,
                            "content": chunk,
                            "metrics": {
                                "output_ttft": round(first_output_time, 4)
                                if first_output_time is not None
                                else None,
                                "output_tokens": output_chunk_count,
                                "thinking_tokens": thinking_chunk_count,
                                "tokens_per_second": round(output_tps, 2),
                                "elapsed": round(elapsed, 4),
                            },
                        }
                    )

                logger.info(
                    "Arena: finished model=%s output_chunks=%d thinking_chunks=%d elapsed=%.2fs",
                    model_name,
                    output_chunk_count,
                    thinking_chunk_count,
                    time.perf_counter() - start,
                )
            except Exception as exc:
                logger.error("Arena: error streaming model=%s: %s", model_name, exc)
                await queue.put(
                    {
                        "model": model_name,
                        "kind": "error",
                        "content": f"[Error: {exc}]",
                        "metrics": None,
                    }
                )
            finally:
                await queue.put({"_done": model_name})

        tasks = [asyncio.create_task(stream_one(m)) for m in body.models]
        done_count = 0
        total = len(body.models)

        while done_count < total:
            event = await queue.get()
            if "_done" in event:
                done_count += 1
                continue
            yield {"event": "token", "data": json.dumps(event)}

        yield {"event": "done", "data": "{}"}

        for t in tasks:
            t.cancel()

    return EventSourceResponse(event_generator())
