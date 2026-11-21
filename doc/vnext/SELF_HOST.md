# Self-hosting BenchBase (vNext)

1. Copy `config/settings.yaml.example` → `config/settings.yaml`.
2. Set OpenAI-compatible `litellm_base_url` / `inference_base_url` (same field; WP9 alias).
3. `docker compose -f docker/docker-compose.yml up --build` (data in `docker/data/`).
4. Run `uv run python scripts/vnext_backup.py` before upgrades.
5. Creative Arena: enable `creative_arena_enabled` in settings after WP7 security review; worker compose optional (`docker/docker-compose.worker.yml`).
6. Mock demo: import packages only via API with `dry_run=true`; no private endpoints in samples.