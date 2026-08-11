# Agentic sole-tenancy checklist

T_eff is only valid when the **inference host** is sole-tenant for the candidate
deployment. Contaminated timing is worse than no number.

## Before launch

1. Stop other benchmark tiers / batch jobs in BenchBase (agentic start refuses a busy queue).
2. Confirm no other inference load on the Spark (no competing vLLM/sparkrun jobs, no Arena traffic).
3. Run harness/checkers/OMP on a **separate** machine from inference when possible.
4. Keep prefix caching enabled and constant across the run.
5. Use `POST /api/benchmarks/agentic/start` only — never Smoke/Standard/Thorough.
6. Concurrency is forced to **1** (serial per deployment).

## MVP vs headline budgets

| Profile | Tasks | Seeds | Approx wall (sole tenant) |
|---------|-------|-------|---------------------------|
| MVP | 8 | 3 | ~1.5–2.5 h |
| Headline | ~20 | 5 | overnight |

Default task timeout 5 min; hard cap 8 min; thrash/spin cutoffs apply.

## After

Record `harness_version` (OMP pin), `suite_version`, provider/profile, and
`package_hash` (placeholder until the estimator store exists).

For **instrument validation** (OpenRouter DeepSeek Flash), sole tenancy on the
Spark is not required — inference is off-box. Still keep the BenchBase queue idle
(concurrency=1). See [`agentic-instrument.md`](agentic-instrument.md).
