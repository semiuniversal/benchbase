"""Simulate speed compare via Arena-style streaming (same client as /api/arena)."""

from __future__ import annotations

import asyncio
import time

from benchbase.litellm_client import LiteLLMClient

MODELS = ["holo3.1", "qwen3.6-35b-nothink"]

MAX_TOKENS = 2048
SYSTEM = (
    "You are running a latency benchmark. Always respond with a short continuation "
    "of the user message."
)
USER = (
    "It was a bright cold day in April, and the clocks were striking thirteen. "
    "Winston Smith, his chin nuzzled into his breast in an effort to escape the vile wind, "
    "slipped quickly through the glass doors of Victory Mansions, though not quickly enough"
)


async def measure(model: str) -> dict:
    client = LiteLLMClient()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER},
    ]
    start = time.perf_counter()
    first_think: float | None = None
    first_output: float | None = None
    last_output: float | None = None
    think_chunks = 0
    output_chunks = 0
    think_chars = 0
    output_chars = 0

    async for kind, text in client.stream_chat(
        model=model,
        messages=messages,
        max_tokens=MAX_TOKENS,
        temperature=0.0,
    ):
        now = time.perf_counter()
        if kind == "thinking":
            think_chunks += 1
            think_chars += len(text)
            if first_think is None:
                first_think = now - start
        elif kind == "content":
            output_chunks += 1
            output_chars += len(text)
            if first_output is None:
                first_output = now - start
            last_output = now

    end = time.perf_counter()
    wall_ms = (end - start) * 1000
    output_completion_ms = ((last_output - start) * 1000) if last_output else wall_ms
    output_elapsed = (last_output - first_output) if (last_output and first_output) else 0
    output_chunk_tps = (
        output_chunks / output_elapsed if output_elapsed > 0 else 0
    )
    mixed_chunk_tps = (think_chunks + output_chunks) / (end - start) if end > start else 0

    return {
        "model": model,
        "wall_ms": round(wall_ms, 1),
        "output_completion_ms": round(output_completion_ms, 1),
        "first_output_ms": round(first_output * 1000, 1) if first_output else None,
        "first_think_ms": round(first_think * 1000, 1) if first_think else None,
        "output_chars": output_chars,
        "think_chars": think_chars,
        "output_chunk_tps": round(output_chunk_tps, 2),
        "mixed_chunk_tps": round(mixed_chunk_tps, 2),
    }


async def main() -> None:
    print(f"Arena-style simulation (max_tokens={MAX_TOKENS}, benchmark system prompt)\n")
    results = await asyncio.gather(*(measure(m) for m in MODELS))
    for r in sorted(results, key=lambda x: x["output_completion_ms"]):
        print(f"=== {r['model']} ===")
        for key, value in r.items():
            if key != "model":
                print(f"  {key}: {value}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
