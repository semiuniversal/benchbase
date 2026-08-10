# Agentic headline report format (internal)

Used after a headline suite (~20 × n=5) completes on a reference deployment.

## Header

- deployment / model name
- `package_hash` (placeholder until estimator store)
- LiteLLM profile / endpoint
- `harness_version` (OMP pin tag)
- `suite_version` (`headline`)
- hardware / sole-tenancy attestation

## Scalars

| Metric | Definition |
|--------|------------|
| pass@1 | fraction of first-seed successes on solvable tasks |
| pass^n | fraction of tasks with ≥1 success in n seeds |
| geo-mean T_eff vs reference | SPEC-style; self-ratio = 1.0 |
| false-confidence | fabrication/non-abstention rate on `expected: unsolvable` probes |
| recovery | success rate on failure-injection tasks |

## Diagnostics (per task)

- P(success), mean wall, T_eff (∞ flagged if P=0)
- tokens/attempt, seconds/token, 1/P
- hashline reject rate, thrash rate

Held-out rotation (Goodhart): process note in `SUITE.json`; not automated.
