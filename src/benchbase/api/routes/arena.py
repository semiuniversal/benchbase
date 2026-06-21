"""Arena mode – simultaneous multi-model prompting with SSE streaming."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from benchbase.litellm_client import LiteLLMClient

router = APIRouter()


class ArenaRequest(BaseModel):
    prompt: str
    models: list[str]
    max_tokens: int = 1024
    temperature: float = 0.7


@router.post("/stream")
async def arena_stream(body: ArenaRequest):
    """Stream responses from multiple models concurrently via SSE."""

    async def event_generator():
        client = LiteLLMClient()
        tasks = []
        for model_name in body.models:
            tasks.append(
                _stream_model(client, model_name, body.prompt, body.max_tokens, body.temperature)
            )

        async def forward_events(model_name: str, aiter):
            async for event in aiter:
                yield event

        queues: dict[str, asyncio.Queue] = {m: asyncio.Queue() for m in body.models}
        done_count = 0
        total = len(body.models)

        async def fill_queue(model_name, aiter):
            async for event in aiter:
                await queues[model_name].put(event)
            await queues[model_name].put(None)

        runners = []
        for model_name in body.models:
            aiter = _stream_model(
                client, model_name, body.prompt, body.max_tokens, body.temperature
            )
            runners.append(asyncio.create_task(fill_queue(model_name, aiter)))

        active = set(body.models)
        while active:
            for model_name in list(active):
                try:
                    event = queues[model_name].get_nowait()
                    if event is None:
                        active.discard(model_name)
                    else:
                        yield {"event": "token", "data": json.dumps(event)}
                except asyncio.QueueEmpty:
                    pass
            if active:
                await asyncio.sleep(0.01)

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_generator())


async def _stream_model(
    client: LiteLLMClient,
    model_name: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
):
    """Yield token events with timing metrics for one model."""
    start = time.perf_counter()
    first_token_time = None
    token_count = 0

    async for chunk in client.stream_chat(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    ):
        now = time.perf_counter()
        if first_token_time is None:
            first_token_time = now - start

        token_count += 1
        elapsed = now - start
        tps = token_count / elapsed if elapsed > 0 else 0

        yield {
            "model": model_name,
            "content": chunk,
            "metrics": {
                "ttft": round(first_token_time, 4),
                "tokens": token_count,
                "tokens_per_second": round(tps, 2),
                "elapsed": round(elapsed, 4),
            },
        }
