# Proposal: Inspect session for Finalist · Agentic

Status: **in progress / core Finalist** — durable + live session visibility is a required Finalist capability (structured RPC transcript; not PTY/xterm). Scoring stays checker/ledger-only; this is the human audit surface.

Companion to [`benchbase-agentic-extension-spec.md`](benchbase-agentic-extension-spec.md). Does not change scoring rules.

## Why

Finalist scores (pass@k, T_eff, tools/turns) answer “did it resolve?” They do not answer “do I *like* how it worked?”

Human judgment over the OMP trajectory — thrash, narration, lucky guesses, recovery after fail-once, abstention quality — is as important as the stats for routing and trust. Trajectories are persisted as JSONL under `data/agentic/{run_id}/` and streamed live via SSE while an attempt runs.

## What we are *not* doing (yet)

- Mixing vibe / human ratings into T_eff or pass rates
- Embedding the real OMP TUI (PTY / xterm.js) — stretch goal below
- Phase C three-actor UI (simulator + agent); Phase A autonomous sessions first
- Snapshotting the mutated live workspace every tool call (v1: immutable fixture view + transcript)

## Affordance

**Inspect session** on Finalist · Agentic runs (per attempt: task + seed).

Dialog contents:

- Left: fixture workspace tree + file viewer (codebase supplied)
- Right: live / historical transcript (instruction → assistant → tools)
- Header: model/label, task, seed, elapsed, tools/turns, PASS/FAIL when known

Judgment stays with the reader. The dialog is an audit surface, not a scorer.

### Instrument validation (operators)

The Finalist **Instrument validation** checkbox means: a remote OpenRouter model **is the agent under test** (harness proof). It is **not** an interlocutor or judge. Scores remain checker-only and must not be read as local UUT ability.

## Data

```text
data/agentic/{run_id}/{task_id}-seed{n}.jsonl
data/agentic/{run_id}/current.json   # live pointer while running
```

`transcript_path` is stored on AttemptLedger / `ResultItem.detail_json`.

## APIs

- `GET /api/benchmarks/runs/{run_id}/agentic/attempts`
- `GET .../attempts/{item_id}/transcript`
- `GET .../attempts/{item_id}/events` (SSE: replay then live)
- `GET .../attempts/{item_id}/workspace` (+ `/workspace/file?path=`)
- `GET .../agentic/current`

## Success criterion

During and after a Finalist run, an operator can open any attempt and reconstruct *what the agent did* — fixture, instruction, tools, assistant text — without SSH.

## Stretch goal: OMP TUI in a browser window

Ambition, not near-term scope: show the **live Oh My Pi terminal UI** inside BenchBase so watching a Finalist attempt feels like sitting at the `omp` TUI — not only a reconstituted chat transcript.

### Why it’s interesting

The TUI is how operators already experience the harness day-to-day. Embedding it would make Finalist runs feel continuous with that workflow and might surface timing/animation cues a flat JSONL view loses.

### Why it’s hard

Finalist drives OMP in **`--mode rpc`**. The interactive TUI expects a **real PTY**. Likely shape: PTY + WebSocket + xterm.js, with RPC remaining the scoring source of truth.

### Placement

Stretch after durable transcripts + Inspect session. Prefer proving audit value with JSONL first.
