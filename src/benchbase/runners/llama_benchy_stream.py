"""Shared helpers for BenchBase llama-benchy stream metric tracking."""

from __future__ import annotations

from typing import Literal

from llama_benchy.client import RequestResult, _warned_about_fallback

StreamKind = Literal["output", "reasoning"]


def init_request_stream_metrics(result: RequestResult) -> None:
    """Attach BenchBase fields for separate output vs thinking measurements."""
    if not hasattr(result, "reasoning_token_timestamps"):
        result.reasoning_token_timestamps = []
        result.reasoning_total_tokens = 0
        result.first_reasoning_token_ts = None


def _stream_fields(result: RequestResult, stream: StreamKind) -> tuple[list[float], str, str]:
    if stream == "output":
        return result.token_timestamps, "first_token_ts", "total_tokens"
    return result.reasoning_token_timestamps, "first_reasoning_token_ts", "reasoning_total_tokens"


def append_stream_tokens(
    result: RequestResult,
    *,
    stream: StreamKind,
    text: str | None,
    token_ids: list[int] | None,
    chunk_time: float,
    tokenizer,
) -> None:
    """Record token timestamps for output or reasoning streams."""
    global _warned_about_fallback

    init_request_stream_metrics(result)
    timestamps, first_ts_attr, total_attr = _stream_fields(result, stream)

    if getattr(result, first_ts_attr) is None:
        setattr(result, first_ts_attr, chunk_time)

    if token_ids:
        count = len(token_ids)
        setattr(result, total_attr, getattr(result, total_attr) + count)
        if count == 1:
            timestamps.append(chunk_time)
            return

        last_ts = timestamps[-1] if timestamps else getattr(result, first_ts_attr)
        if last_ts is None:
            last_ts = result.start_ts
        time_window = chunk_time - last_ts
        for i in range(count):
            ts = last_ts + (time_window * (i + 1) / count)
            timestamps.append(ts)
        return

    if tokenizer is not None and text:
        if not _warned_about_fallback:
            print("  No token_ids in response, using local tokenization")
            _warned_about_fallback = True

        count = len(tokenizer.encode(text, add_special_tokens=False))
        setattr(result, total_attr, getattr(result, total_attr) + count)
        if count == 1:
            timestamps.append(chunk_time)
            return

        last_ts = timestamps[-1] if timestamps else getattr(result, first_ts_attr)
        if last_ts is None:
            last_ts = result.start_ts
        time_window = chunk_time - last_ts
        for i in range(count):
            ts = last_ts + (time_window * (i + 1) / count)
            timestamps.append(ts)
        return

    if text:
        if not _warned_about_fallback:
            print("  No token_ids or tokenizer, assuming 1 token per chunk")
            _warned_about_fallback = True
        setattr(result, total_attr, getattr(result, total_attr) + 1)
        timestamps.append(chunk_time)


def count_tokens_after_first(timestamps: list[float]) -> int:
    if len(timestamps) < 2:
        return 0
    first_ts = timestamps[0]
    return sum(1 for ts in timestamps if ts > first_ts)


def throughput_from_timestamps(
    timestamps: list[float],
    *,
    start_ts: float,
    first_ts: float | None,
    total_tokens: int | None = None,
) -> tuple[float | None, float | None, float | None]:
    """Return decode-window tok/s, TTFT (s), and decode duration (s).

    Decode window is first visible token through last visible token only.
    """
    if not timestamps or first_ts is None:
        return None, None, None

    ttft = first_ts - start_ts
    if len(timestamps) < 2:
        return None, ttft, None

    decode_time = timestamps[-1] - timestamps[0]
    decode_tokens = count_tokens_after_first(timestamps)
    if total_tokens is not None and total_tokens > 1:
        decode_tokens = total_tokens - 1
    if decode_time <= 0 or decode_tokens <= 0:
        return None, ttft, decode_time if decode_time > 0 else None

    return decode_tokens / decode_time, ttft, decode_time


def effective_visible_throughput(
    timestamps: list[float],
    *,
    start_ts: float,
    first_ts: float | None,
    total_tokens: int | None = None,
) -> tuple[float | None, float | None, float | None, int]:
    """Return effective visible tok/s, TTFT (s), completion time (s), token count.

    Effective tok/s = visible_tokens / wall time from request start to last visible
    token. Thinking time is included in the denominator; thinking tokens are excluded
    from the numerator.
    """
    if first_ts is None:
        return None, None, None, 0

    token_count = total_tokens if total_tokens is not None else len(timestamps)
    if token_count <= 0:
        return None, None, None, 0

    last_ts = timestamps[-1] if timestamps else first_ts
    ttft = first_ts - start_ts
    completion_time = last_ts - start_ts
    if completion_time <= 0:
        return None, ttft, None, token_count

    return token_count / completion_time, ttft, completion_time, token_count
