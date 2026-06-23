"""Arena mode – simultaneous multi-model prompting."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from benchbase.litellm_client import LiteLLMClient

logger = logging.getLogger(__name__)
router = APIRouter()


class ArenaRequest(BaseModel):
    prompt: str = Field(description="User message sent to each model.")
    models: list[str] = Field(description="LiteLLM model IDs to query in parallel.")
    max_tokens: int | None = Field(
        default=None,
        description="Maximum completion tokens per model (optional).",
    )
    temperature: float = Field(
        default=0.7,
        description="Sampling temperature for completions.",
    )


class ArenaChatResponseItem(BaseModel):
    model: str
    content: str | None = None
    error: str | None = None


class ArenaChatResponse(BaseModel):
    responses: list[ArenaChatResponseItem]


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
async def arena_chat(body: ArenaRequest) -> ArenaChatResponse:
    client = LiteLLMClient()
    messages = [{"role": "user", "content": body.prompt}]

    async def chat_one(model_name: str) -> ArenaChatResponseItem:
        try:
            result = await client.chat(
                model=model_name,
                messages=messages,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
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
async def arena_stream(body: ArenaRequest):
    """Stream responses from multiple models concurrently via SSE."""

    async def event_generator():
        client = LiteLLMClient()
        queue: asyncio.Queue = asyncio.Queue()

        async def stream_one(model_name: str):
            logger.info("Arena: starting stream for model=%s", model_name)
            start = time.perf_counter()
            first_token_time = None
            token_count = 0

            try:
                async for kind, chunk in client.stream_chat(
                    model=model_name,
                    messages=[{"role": "user", "content": body.prompt}],
                    max_tokens=body.max_tokens,
                    temperature=body.temperature,
                ):
                    now = time.perf_counter()
                    if first_token_time is None:
                        first_token_time = now - start
                        logger.info(
                            "Arena: first token from model=%s ttft=%.3fs",
                            model_name, first_token_time,
                        )

                    token_count += 1
                    elapsed = now - start
                    tps = token_count / elapsed if elapsed > 0 else 0

                    await queue.put({
                        "model": model_name,
                        "kind": kind,
                        "content": chunk,
                        "metrics": {
                            "ttft": round(first_token_time, 4),
                            "tokens": token_count,
                            "tokens_per_second": round(tps, 2),
                            "elapsed": round(elapsed, 4),
                        },
                    })

                logger.info(
                    "Arena: finished model=%s tokens=%d elapsed=%.2fs",
                    model_name, token_count, time.perf_counter() - start,
                )
            except Exception as exc:
                logger.error("Arena: error streaming model=%s: %s", model_name, exc)
                await queue.put({
                    "model": model_name,
                    "content": f"\n\n[Error: {exc}]",
                    "metrics": None,
                })
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
