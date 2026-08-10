# How we publish agentic / Harbor / τ² results

## Phase A (OMP autonomous)

- Engine: pinned Oh My Pi (`third_party/omp`, see `doc/omp-pin.md`).
- Metrics: pass@1, pass^n, T_eff, false-confidence, recovery — from AttemptLedger + checkers.
- Launch: `POST /api/benchmarks/agentic/start` (finalist only).

## Phase B (publishable track)

Harbor/EvoCode and τ² run on their **native** harnesses. BenchBase does not
reimplement them inside OMP. We attach an **operational ledger** side-car that
shares schema with Phase A fields needed for timing/tokens/package identity.

```python
from benchbase.publishable.harbor_wrapper import run_harbor_with_ledger
from benchbase.publishable.tau2_wrapper import run_tau2_with_ledger

ledger = run_harbor_with_ledger(
    suite_name="evocode-sample",
    command=["harbor", "run", "..."],  # verbatim native argv
    sidecar_path="artifacts/harbor_ledger.json",
    package_hash="...",
    litellm_profile="http://litellm:4000/v1",
)
```

Checkpoint B1: one published suite run → native metrics + `*_ledger.json`.  
Checkpoint B2: this note.

## What we do not mix

- Interactive / judged conversation quality (Phase C) never enters T_eff.
- Radar spokes remain capability axes; T_eff is a finalist plate / scalar.
