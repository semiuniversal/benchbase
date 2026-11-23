# Dashboard headlines — D0 route / source matrix

**Spec:** `DASHBOARD-ACTIONABLE-HEADLINES-v1` · **Scope:** D0 + D1 (benchmark only)

| Type | Source (persisted) | Record key | Destination | Ship D1 |
|---|---|---|---|---|
| `benchmark.running` | `Run.status` ∈ running/pausing; grouped by `run_group_id` | `group:{run_group_id}` or `solo:{run_id}` | `/benchmarks?group=…&open=1` (live log modal) | Yes |
| `benchmark.queued` | Group rollup `pending`; batch `pending_count` only as queue context | same | `/benchmarks?group=…&open=1` | Yes |
| `benchmark.completed` | All members `completed`; group not finalist/agentic | `group:{run_group_id}` | `/benchmarks?group=…&open=1` (results in log modal) | Yes |
| `benchmark.interrupted` | `failed` / `paused` / `cancelled` groups | `group:{run_group_id}` | `/benchmarks?group=…&open=1` | Yes |
| `creative.*` | Creative attempt store | attempt id | `/creative?…` | **No** (D2) |
| `finding.*` | Scorecard / Compare | — | `/compare?…` | **No** (D3) |

**Consolidation:** One headline per `run_group_id` (tier sitting), not per axis `Run`.

**Excluded:** Agentic/finalist groups; model health / inactive inventory; lifetime KPIs.

**API:** `GET /api/dashboard/headlines` → `{ headlines: DashboardHeadline[], generated_at }`.

**Deep-link fix:** Benchmarks page honors `?group=` and `?run_id=` (+ `open=1`) on load.