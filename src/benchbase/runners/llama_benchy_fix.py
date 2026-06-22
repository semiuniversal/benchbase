"""Patch llama-benchy SSE parsing so thinking-model streams are measured correctly.

llama-benchy 0.3.x uses codecs.incrementaldecoder with aiohttp iter_any(), which
drops most SSE chunks on some backends. Token timestamps never accumulate, so
throughput metrics stay null even when reasoning_content streams successfully.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

from llama_benchy.client import LLMClient, RequestResult, _warned_about_fallback


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

                    if line.startswith("data:"):
                        try:
                            json_str = line[5:].strip()
                            chunk = json.loads(json_str)

                            if "usage" in chunk and chunk["usage"] is not None:
                                result.prompt_tokens = chunk["usage"].get("prompt_tokens", 0)

                            if "choices" in chunk and len(chunk["choices"]) > 0:
                                if result.first_response_ts is None:
                                    result.first_response_ts = chunk_time

                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content")
                                reasoning_content = delta.get("reasoning_content")
                                reasoning = delta.get("reasoning")

                                if content or reasoning_content or reasoning:
                                    if result.first_token_ts is None:
                                        result.first_token_ts = chunk_time

                                    token_ids = chunk["choices"][0].get("token_ids")
                                    if token_ids and isinstance(token_ids, list):
                                        result.total_tokens += len(token_ids)
                                        if len(token_ids) == 1:
                                            result.token_timestamps.append(chunk_time)
                                        else:
                                            last_ts = (
                                                result.token_timestamps[-1]
                                                if result.token_timestamps
                                                else result.first_token_ts
                                            )
                                            if last_ts is None:
                                                last_ts = result.start_ts
                                            time_window = chunk_time - last_ts
                                            for i in range(len(token_ids)):
                                                ts = last_ts + (time_window * (i + 1) / len(token_ids))
                                                result.token_timestamps.append(ts)
                                    elif tokenizer is not None:
                                        global _warned_about_fallback
                                        if not _warned_about_fallback:
                                            print("  No token_ids in response, using local tokenization")
                                            _warned_about_fallback = True

                                        full_content = content or reasoning_content or reasoning
                                        token_count = len(
                                            tokenizer.encode(full_content, add_special_tokens=False)
                                        )
                                        result.total_tokens += token_count
                                        if token_count == 1:
                                            result.token_timestamps.append(chunk_time)
                                        else:
                                            last_ts = (
                                                result.token_timestamps[-1]
                                                if result.token_timestamps
                                                else result.first_token_ts
                                            )
                                            if last_ts is None:
                                                last_ts = result.start_ts
                                            time_window = chunk_time - last_ts
                                            for i in range(token_count):
                                                ts = last_ts + (time_window * (i + 1) / token_count)
                                                result.token_timestamps.append(ts)
                                    else:
                                        if not _warned_about_fallback:
                                            print("  No token_ids or tokenizer, assuming 1 token per chunk")
                                            _warned_about_fallback = True

                                        result.total_tokens += 1
                                        result.token_timestamps.append(chunk_time)
                        except json.JSONDecodeError:
                            continue

            result.end_ts = time.perf_counter()

    except Exception as e:
        print(f"Error during run: {e}")
        result.error = str(e)

    return result


def apply_llama_benchy_stream_fix() -> None:
    """Replace broken SSE parser on llama-benchy's LLMClient (safe to call repeatedly)."""
    LLMClient.run_generation = _run_generation_fixed
