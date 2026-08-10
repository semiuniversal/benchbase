# tiny_service fixture

In-process mini service for agentic edit/config tasks.

Seams:
- `app/server.py` — `/health` payload shape
- `app/config.py` / `config.toml` — port, CORS
- `app/locks.py` — fail-once write for recovery tasks
