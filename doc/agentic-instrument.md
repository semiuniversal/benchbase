# Instrument LLM vs unit under test (UUT)

BenchBase agentic evaluation separates two roles:

| Role | What | Where |
|------|------|--------|
| **UUT** | Local deployment being scored (LiteLLM → vLLM/sparkrun) | Sole-tenant Sparks |
| **Instrument** | Third-party LLM used for harness proof, user simulator, and binarized judge | OpenRouter |

## Locked instrument

- Provider: OpenRouter (`https://openrouter.ai/api/v1`)
- Model: `deepseek/deepseek-v4-flash-0731`
- Secret: `OPENROUTER_API_KEY` in repo `.env` (gitignored) and compose env

Never use a local model that is itself under evaluation as simulator, judge, or
harness-validation agent. That contaminates the instrument.

## Phase A — harness proof

`POST /api/benchmarks/agentic/start` with:

```json
{
  "model_id": <any-active-db-model-id>,
  "suite_version": "mvp",
  "n_seeds": 1,
  "instrument_validation": true,
  "omp_provider": "openrouter",
  "omp_model": "deepseek/deepseek-v4-flash-0731"
}
```

OMP talks to OpenRouter directly (`~/.omp/agent/models.json` provider `openrouter`).
Results are labeled instrument validation — not a local UUT ranking.

## Phase C — interlocutor + judge

[`src/benchbase/agentic/openrouter_client.py`](../src/benchbase/agentic/openrouter_client.py):

- `UserSimulator` — stimulus only (card release policy); never a judge
- `BinarizedJudge` — YES/NO rubric items only; **never** blended into T_eff

## Env

See [`.env.example`](../.env.example). Compose passes `OPENROUTER_API_KEY` /
`OPENROUTER_MODEL` into the BenchBase container.
