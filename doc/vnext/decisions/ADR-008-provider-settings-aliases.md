# ADR-008: Provider-neutral settings via inference URL alias

**Status:** accepted  
**Date:** 2026-11-21  
**Work packages:** WP9

## Context

LLManifold is OpenAI-compatible; spec forbids new LiteLLM dependency and asks for neutral naming while preserving stored keys.

## Decision

- Keep persisted **`litellm_base_url`** / **`litellm_api_key`** for backward compatibility.
- Add optional **`inference_base_url`**; when set, [`load_settings`](../../../src/benchbase/config.py) copies it into `litellm_base_url` for the client.
- UI copy may say “Inference gateway” over time; no rename migration of DB keys in WP9.

## Consequences

- Self-host docs can document `inference_base_url` without implying LiteLLM.
- Full UI relabel is cosmetic and can trail API alias.