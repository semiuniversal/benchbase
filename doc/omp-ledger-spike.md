# OMP ledger spike (v9.8.0)

**Pin:** `third_party/omp` @ **v9.8.0** (`a37b5f4b988cd44ec6262b37cd9c5be50327739a`)  
**Date:** 2026-08-10  
**Method:** Source inspection of Oh My Pi coding-agent (`--mode rpc`, `--mode json` / print mode, session JSONL under `~/.omp/agent/sessions/`). Live model run deferred until Bun install on the agentic runner host; CI uses fixture transcripts.

## Verdict: **PASS** (go for Phase A)

Every AttemptLedger field is available via **RPC/print JSON events** and/or **on-disk session files**. No harness rebuild required.

| Field | Available? | Source |
|-------|------------|--------|
| wall seconds | Yes | Driver wall-clock around prompt→idle; RPC `get_session_stats` / session timestamps |
| turns, tool calls | Yes | Session events: assistant/tool_call/tool_result JSONL; RPC streams same via `session.subscribe` |
| hashline rejected edits | Yes | Edit tool results in events/session (stale-anchor failures); also `scripts/dump-edit-history.ts` over session JSONL |
| token usage (prompt+completion+thinking) | Yes | Assistant message `usage` in session; `SessionManager` aggregates input/output/cache; RPC `get_session_stats` |
| turn-end / session resume | Yes | Agent idle after prompt; RPC `switch_session` / `new_session`; session file path in `RpcSessionState.sessionFile` |
| prompt injection of task instruction | Yes | RPC command `{ "type": "prompt", "message": "..." }` on stdin |

## Protocol notes

- **RPC mode:** `omp --mode rpc` — JSON lines on stdin (commands), JSON lines on stdout (events + `{type:"response",...}`).
- **Print/JSON mode:** `omp --mode json -p "…"` — single-shot event stream (good for smoke tests).
- **SDK:** `createAgentSession()` in `@oh-my-pi/pi-coding-agent/sdk` for in-process control if preferred later.
- **Sessions dir:** `~/.omp/agent/sessions/**/*.jsonl` (fallback when live event parsing misses a field).

## Gaps / operational caveats (non-blocking)

- Bun ≥1.3.7 required to build/run OMP; BenchBase API container does not bundle it yet — run OMP on the **agentic runner host**.
- Hashline rejection strings are tool-result text; BenchBase parser must classify them (keyword / structured error) rather than a dedicated RPC field.
- Thinking tokens appear in usage when the model/provider exposes them; otherwise count as 0.

## Next

Phase 0.3 driver stub parses fixture transcripts into `AttemptLedger`; live sole-tenant smoke follows A3.
