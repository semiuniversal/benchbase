"""Patch llama-benchy SSE parsing for OpenAI-compatible streaming backends.

Fixes dropped SSE chunks and splits measurements into:
- output: visible content tokens (used for speed ranking)
- reasoning: hidden thinking tokens and time-to-first-think (informational)
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

from llama_benchy.client import LLMClient, RequestResult

from benchbase.runners.llama_benchy_stream import append_stream_tokens, init_request_stream_metrics


_BENCHMARK_SYSTEM = (
    "You are running a latency benchmark. Always respond with a short continuation "
    "of the user message."
)


async def _run_generation_fixed(
    self: LLMClient,
    session: aiohttp.ClientSession,
    context_text: str,
    prompt_text: str,
    max_tokens: int,
    no_cache: bool,
    tokenizer=None,
) -> RequestResult:
    messages = []
    system_parts = [_BENCHMARK_SYSTEM]
    if context_text:
        system_parts.append(context_text)
    messages.append({"role": "system", "content": "\n\n".join(system_parts)})
    messages.append({"role": "user", "content": prompt_text})

    result = RequestResult()
    init_request_stream_metrics(result)

    try:
        payload = self._build_generation_payload(messages, max_tokens, no_cache)

        result.start_ts = time.perf_counter()

        async with session.post(
            f"{self.base_url}/chat/completions", json=payload, headers=self.headers
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                result.error = f"HTTP {response.status}: {error_text}"
                print(result.error)
                _log_generation_result(result)
                return result

            buffer = ""
            async for chunk_bytes in response.content.iter_any():
                chunk_time = time.perf_counter()
                buffer += chunk_bytes.decode(errors="replace")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    if line == "data: [DONE]" or line == "data:[DONE]":
                        continue

                    if not line.startswith("data:"):
                        continue

                    try:
                        json_str = line[5:].strip()
                        chunk = json.loads(json_str)

                        if "usage" in chunk and chunk["usage"] is not None:
                            result.prompt_tokens = chunk["usage"].get("prompt_tokens", 0)

                        if "choices" not in chunk or not chunk["choices"]:
                            continue

                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content")
                        reasoning_content = delta.get("reasoning_content")
                        reasoning = delta.get("reasoning")
                        reasoning_text = reasoning_content or reasoning
                        token_ids = chunk["choices"][0].get("token_ids")

                        if content or reasoning_text:
                            if result.first_response_ts is None:
                                result.first_response_ts = chunk_time

                        if reasoning_text and not content:
                            append_stream_tokens(
                                result,
                                stream="reasoning",
                                text=reasoning_text,
                                token_ids=token_ids if isinstance(token_ids, list) else None,
                                chunk_time=chunk_time,
                                tokenizer=tokenizer,
                            )

                        if content:
                            append_stream_tokens(
                                result,
                                stream="output",
                                text=content,
                                token_ids=token_ids if isinstance(token_ids, list) else None,
                                chunk_time=chunk_time,
                                tokenizer=tokenizer,
                            )
                    except json.JSONDecodeError:
                        continue

            result.end_ts = time.perf_counter()

    except Exception as e:
        print(f"Error during run: {e}")
        result.error = str(e)

    _log_generation_result(result)
    return result


def _log_generation_result(result: RequestResult) -> None:
    """Print a newline-delimited progress line (captured by subprocess log pump)."""
    if result.error:
        print(f"  request failed: {result.error}", flush=True)
        return
    if not result.end_ts or result.start_ts is None:
        return

    wall_ms = (result.end_ts - result.start_ts) * 1000
    out_tokens = getattr(result, "total_tokens", 0) or len(result.token_timestamps or [])
    think_tokens = getattr(result, "reasoning_total_tokens", 0) or 0
    parts = [f"  done: {wall_ms:.0f}ms wall"]

    if out_tokens and result.first_token_ts and result.token_timestamps:
        gen_ms = (result.token_timestamps[-1] - result.first_token_ts) * 1000
        ttft_ms = (result.first_token_ts - result.start_ts) * 1000
        tps = (out_tokens - 1) / (gen_ms / 1000) if gen_ms > 0 and out_tokens > 1 else None
        parts.append(f"output={out_tokens} tok, TTFT={ttft_ms:.0f}ms, decode={gen_ms:.0f}ms")
        if tps is not None:
            parts.append(f"{tps:.1f} out tok/s")
    elif think_tokens:
        parts.append(f"no visible output ({think_tokens} think tokens only)")
    elif out_tokens:
        parts.append(f"output={out_tokens} tok")
    else:
        parts.append("empty response")

    print(", ".join(parts), flush=True)


def apply_llama_benchy_stream_fix() -> None:
    """Replace broken SSE parser on llama-benchy's LLMClient (safe to call repeatedly)."""
    LLMClient.run_generation = _run_generation_fixed
