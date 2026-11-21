# Creative Arena — ZooCode research → OpenCode tools (WP7)

BenchBase vNext uses **OpenCode only** as the creative harness (spec §11.1). ZooCode on revenant is a **reference** for which capabilities the volcano agent needs—not a runtime dependency.

## Capability map (target OpenCode permissions / skills)

| Creative need | ZooCode-style capability | OpenCode v2 mapping | BenchBase worker |
|---------------|-------------------------|---------------------|------------------|
| Edit project files | Workspace file tools | `action: edit`, resource `project/**` → `allow` | Sandboxed attempt dir only |
| Install / build | Terminal (`npm`, `vite`) | `action: shell`, allowlist `npm *`, `npx *`, deny `git push *` | Worker container, no host socket |
| Read-only inspection | Read files | `action: read`, `project/**` → `allow` | UI source viewer (existing) |
| Browser / visual check | Playwright skill (Kasm embed) | OpenCode **skill** or MCP browser tool; pin in `opencode.jsonc` | Phase 4 validation worker (future) |
| Screenshots | Kasm / Playwright capture | Logged `tool.use` events + `media/` artifacts | Post-run only, not in agent DOM |

Kasm/Playwright details from the owner’s ZooCode setup must be **re-authored** as:

1. An OpenCode **skill** definition (documented tool IDs + permission rules), or  
2. An MCP server with scoped `tool.use` rules (`mcp_playwright_*` → `ask` / `allow` in sandbox).

Do not copy Cursor/ZooCode extension config into BenchBase verbatim.

## Translated skills (repo)

| Skill ID | Source intent | Path |
|----------|---------------|------|
| `volcano-build` | Volcano challenge brief + canvas workflow | `corpus/creative/opencode/skills/volcano-build/SKILL.md` |
| `creative-shell` | ZooCode terminal / npm guardrails | `corpus/creative/opencode/skills/creative-shell/SKILL.md` |
| `creative-browser-check` | Playwright/Kasm visual validation | `corpus/creative/opencode/skills/creative-browser-check/SKILL.md` |

Provisioned into each attempt as `.opencode/skills/`; referenced from workspace `opencode.jsonc` (`skills` array + `volcano-builder` skill permissions).

## Per-attempt layout

See spec §11.5. Implemented in `benchbase.creative.workspace.provision_attempt_workspace`.

```
{BENCHBASE_DATA_DIR}/creative/volcano-skunk-v1/{attempt_uuid}/
  manifest.json
  opencode.jsonc      # copied from corpus template + model override
  project/
  logs/events.jsonl   # harness events (mock or live OpenCode)
  build/
  evidence/
  media/
```

## Config template

[`corpus/creative/opencode/volcano-agent.jsonc`](../../corpus/creative/opencode/volcano-agent.jsonc) is copied into each workspace. Update when OpenCode pin changes (ADR-006).

## Test matrix (before live OpenCode)

| Step | Command / check |
|------|-----------------|
| Mock stream | `pytest tests/test_creative_mock_runner.py` |
| Workspace paths | `pytest tests/test_creative_workspace.py` |
| UI monitor | Creative → start attempt → log + file tree + preview iframe |
| Short live (owner) | Install pinned OpenCode in worker image; `opencode_driver.run_attempt` against LLManifold seat; capture `logs/events.jsonl` |
| Browser tool | After skill translation: one headed/headless screenshot into `media/`; verify permission rules block host paths |

## Open questions (owner)

- Exact OpenCode version pin for revenant worker image  
- Whether Playwright runs inside worker via MCP or bundled skill  
- Kasm only needed if headed browser must be human-visible; headless Playwright may suffice for validation