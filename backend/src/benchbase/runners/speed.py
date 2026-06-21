"""Speed / throughput benchmark runner."""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.db.models import Result, Run
from benchbase.litellm_client import LiteLLMClient
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner

WARMUP_PROMPT = "Say hello."
BENCH_PROMPTS = [
    "Explain the theory of relativity in simple terms.",
    "Write a Python function that computes the Fibonacci sequence iteratively.",
    "Summarize the plot of Hamlet in three sentences.",
]


@register_runner("speed")
class SpeedRunner(BenchmarkRunner):
    """Measures latency, TTFT, and generation throughput."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        client = LiteLLMClient()
        model_name = run.model.name

        # Warmup request (discarded)
        await client.chat(model=model_name, messages=[{"role": "user", "content": WARMUP_PROMPT}])

        for prompt in BENCH_PROMPTS:
            metrics = await self._timed_request(client, model_name, prompt)
            result = Result(
                run_id=run.id,
                task_name=f"speed:{prompt[:40]}",
                score=metrics["tokens_per_second"],
                metrics_json=json.dumps(metrics),
            )
            db.add(result)

        await db.commit()

    async def _timed_request(
        self, client: LiteLLMClient, model: str, prompt: str
    ) -> dict[str, Any]:
        start = time.perf_counter()
        first_token_time = None
        token_count = 0

        async for _chunk in client.stream_chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.0,
        ):
            if first_token_time is None:
                first_token_time = time.perf_counter() - start
            token_count += 1

        elapsed = time.perf_counter() - start
        return {
            "ttft": round(first_token_time or elapsed, 4),
            "total_tokens": token_count,
            "elapsed_seconds": round(elapsed, 4),
            "tokens_per_second": round(token_count / elapsed, 2) if elapsed > 0 else 0,
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Speed Benchmark",
            "category": "speed",
            "description": "Measures latency, TTFT, and generation throughput via streaming requests.",
        }
