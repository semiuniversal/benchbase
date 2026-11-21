# ADR-002: Arena never labels stream chunks as tokens

**Status:** accepted  
**Date:** 2026-11-21  
**Work packages:** WP2

## Context

Arena previously reported `output_chunk_count / elapsed` as `tokens_per_second` and `output_tokens`, which mislabeled chunk rate as TPS (spec §8.1).

## Decision

- Centralize accumulation in [`ArenaStreamAccumulator`](../../../src/benchbase/metrics/arena_stream.py).
- **Decode TPS** is emitted only when streaming `usage.completion_tokens` is present (`decode_rate_method: provider_usage`).
- **Chunk rate** is always separate (`output_chunk_rate_per_s`, `output_chunk_rate_method: stream_chunks`).
- UI shows em dash or chunk/s tooltip when token rate is unknown; never use `0` for missing usage.
- Request `stream_options.include_usage` on chat completions; yield `usage` events from [`litellm_client.stream_chat`](../../../src/benchbase/litellm_client.py).

## Consequences

- Historical Arena observations in logs (if any) remain legacy-labeled; new streams are correct.
- Backends that omit usage will show honest “unknown” token metrics until tokenizer fallback is added (future ADR if implemented).