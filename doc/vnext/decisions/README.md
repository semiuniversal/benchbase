# Architectural decision records (vNext)

Lightweight ADRs keep phases aligned. **Status:** `proposed` · `accepted` · `superseded`.

| ID | Decision | Status | WP |
|----|----------|--------|-----|
| [ADR-001](ADR-001-ranking-cohorts.md) | Default Borda pool = completed standard/thorough only | accepted | WP1 |
| [ADR-002](ADR-002-arena-metric-provenance.md) | Arena decode rate requires provider usage; chunks are diagnostic only | accepted | WP2 |
| [ADR-003](ADR-003-evidence-sqlite-plus-artifacts.md) | Observation metadata in SQLite; payloads under `data/artifacts/` | accepted | WP3 |
| [ADR-004](ADR-004-schema-init-db-then-alembic.md) | Extend `init_db()` for vNext tables; introduce Alembic before breaking changes | accepted | WP3 |
| [ADR-005](ADR-005-creative-feature-flags.md) | Creative Arena and code execution off by default until security gates | accepted | WP7–WP8 |
| [ADR-006](ADR-006-opencode-mock-vs-live.md) | CI uses mock harness; live OpenCode behind owner-approved integration | accepted | WP7 |
| [ADR-007](ADR-007-adapter-registry.md) | Upstream evaluators behind `adapters/` registry + settings flag | accepted | WP6 |
| [ADR-008](ADR-008-provider-settings-aliases.md) | `inference_base_url` aliases `litellm_base_url`; no LiteLLM dependency | accepted | WP9 |
| [ADR-009](ADR-009-export-redaction-default.md) | Export packages redact secrets; import stays inert until explicit persist | accepted | WP9 |
| [ADR-010](ADR-010-retire-agentic-finalist-ui.md) | Remove Agentic Finalist UI; Creative Arena replaces interactive coding benchmark | accepted | WP5, WP8 |

## How to add an ADR

1. Copy [ADR-000-template.md](ADR-000-template.md).
2. Number sequentially; link from this table and from the relevant `plans/WP*.md`.
3. If a later phase contradicts an ADR, add a new ADR that **supersedes** the old one (do not silently drift).