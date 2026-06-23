# BenchBase: CLI → Docker / Portainer migration

Agent- and human-followable guide. Replace `REPO` with the absolute path to the BenchBase clone on the Docker host (e.g. `/home/user/benchbase`).

## Prerequisites

| Variable | Example | Meaning |
|----------|---------|---------|
| `REPO` | `/home/user/benchbase` | Git clone root on the host |
| `DATA` | `$REPO/docker/data` | Persistent DB + logs (bind mount) |
| `CONFIG` | `$REPO/config` | `settings.yaml` directory (bind mount) |

**Rules**

- Only **one** BenchBase process may use `DATA` at a time (no simultaneous `benchbase serve` on the host and Docker).
- Never mount `/app/data` read-only — SQLite needs WAL files.
- `config/settings.yaml` is local-only (not in git). Use `config/settings.yaml.example` as template.

---

## Phase 1 — Stop CLI and migrate data

Run on the host where BenchBase currently runs.

```bash
export REPO=/path/to/benchbase   # REQUIRED: set your clone path

# 1. Stop CLI server (if running)
cd "$REPO"
uv run benchbase stop || true
# Also stop any manual uvicorn on port 8000/8099 if benchbase stop reports nothing.

# 2. Create Docker data directory
mkdir -p "$REPO/docker/data"

# 3. Move CLI database and logs into Docker data dir (skip missing files)
[ -f "$REPO/benchbase.db" ] && mv "$REPO/benchbase.db" "$REPO/docker/data/"
[ -f "$REPO/benchbase.db-wal" ] && mv "$REPO/benchbase.db-wal" "$REPO/docker/data/"
[ -f "$REPO/benchbase.db-shm" ] && mv "$REPO/benchbase.db-shm" "$REPO/docker/data/"
[ -d "$REPO/run_logs" ] && mv "$REPO/run_logs" "$REPO/docker/data/"

# 4. Settings file
if [ ! -f "$REPO/config/settings.yaml ]; then
  cp "$REPO/config/settings.yaml.example" "$REPO/config/settings.yaml"
fi

# 5. Verify data present
ls -la "$REPO/docker/data/"
test -f "$REPO/docker/data/benchbase.db" && echo "OK: database found" || echo "WARN: no benchbase.db yet (fresh install)"
```

**Verification:** `benchbase.db` should live at `$REPO/docker/data/benchbase.db`, not `$REPO/benchbase.db`.

---

## Phase 2 — Configure settings for Docker

Edit `$REPO/config/settings.yaml`:

1. Set `litellm_base_url` to reach LiteLLM **from inside the container**:
   - `http://host.docker.internal:4000` (Linux Docker 20.10+ with `extra_hosts` in compose)
   - or `http://<docker-host-LAN-IP>:4000`
2. Set `litellm_api_key` (or save via Settings UI after first boot).
3. Leave `database_url` as `sqlite+aiosqlite:///benchbase.db` — compose env `BENCHBASE_DB_URL` overrides it in the container.

---

## Phase 3 — Portainer stack (complete compose)

### Option A — Deploy from Git repository (recommended)

In Portainer: **Stacks → Add stack → Repository**

| Field | Value |
|-------|--------|
| Repository URL | your BenchBase git URL |
| Compose path | `docker/docker-compose.yml` |
| Branch | `main` |

**Stack environment variables** (Portainer → Environment variables):

```env
BENCHBASE_HOST_DATA=/path/to/benchbase/docker/data
BENCHBASE_HOST_CONFIG=/path/to/benchbase/config
BENCHBASE_PORT=8000
```

Use **absolute** paths on the Portainer host.

**Complete compose file** (same as repo `docker/docker-compose.yml`):

```yaml
# BenchBase — Portainer / Docker Compose
# Set BENCHBASE_HOST_DATA and BENCHBASE_HOST_CONFIG to absolute host paths.

services:
  benchbase:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    image: benchbase:local
    container_name: benchbase
    ports:
      - "${BENCHBASE_PORT:-8000}:8000"
    volumes:
      - ${BENCHBASE_HOST_DATA:-./data}:/app/data
      - ${BENCHBASE_HOST_CONFIG:-../config}:/app/config
    environment:
      BENCHBASE_DATA_DIR: /app/data
      BENCHBASE_DB_URL: sqlite+aiosqlite:////app/data/benchbase.db
    extra_hosts:
      - "host.docker.internal:host-gateway"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8000/api/settings/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped
    deploy:
      replicas: 1
```

Deploy the stack. Portainer builds from `docker/Dockerfile` with context = repository root.

### Option B — Portainer Web editor (pre-built image)

If Portainer cannot build from git, build on the host once:

```bash
export REPO=/path/to/benchbase
docker build -f "$REPO/docker/Dockerfile" -t benchbase:local "$REPO"
```

Paste this compose in **Stacks → Web editor** (no `build` section):

```yaml
services:
  benchbase:
    image: benchbase:local
    container_name: benchbase
    ports:
      - "${BENCHBASE_PORT:-8000}:8000"
    volumes:
      - ${BENCHBASE_HOST_DATA}:/app/data
      - ${BENCHBASE_HOST_CONFIG}:/app/config
    environment:
      BENCHBASE_DATA_DIR: /app/data
      BENCHBASE_DB_URL: sqlite+aiosqlite:////app/data/benchbase.db
    extra_hosts:
      - "host.docker.internal:host-gateway"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8000/api/settings/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped
```

Set the same three environment variables in Portainer before deploy.

---

## Phase 4 — Post-deploy verification

```bash
# Health (from host)
curl -fsS http://localhost:8000/api/settings/ | head -c 200

# Container health
docker ps --filter name=benchbase

# UI: http://<host>:8000
# MCP: http://<host>:8000/mcp
```

In the web UI: **Settings** → confirm LiteLLM URL and API key → **Discover Models** or **Re-check Health**.

**Success criteria**

- [ ] Container status `healthy`
- [ ] Settings API returns JSON with `litellm_api_key_set`
- [ ] Dashboard shows prior runs (if DB was migrated)
- [ ] Model discovery works against LiteLLM

---

## Phase 5 — Database backup and restore

### When to back up

- Before major upgrades or stack rebuilds
- Before migrating hosts
- On a schedule (e.g. daily cron)

### Backup procedure (safe for SQLite)

SQLite WAL mode requires copying the main DB **and** WAL sidecars together, or backing up while the container is stopped.

**Method 1 — Full data directory (recommended)**

```bash
export REPO=/path/to/benchbase
export DATA="$REPO/docker/data"
export BACKUP_DIR="$REPO/backups"   # optional dedicated backup folder
mkdir -p "$BACKUP_DIR"

cd "$REPO/docker"
docker compose stop benchbase

tar -czf "$BACKUP_DIR/benchbase-data-$(date +%Y%m%d-%H%M%S).tar.gz" -C "$REPO/docker" data

docker compose start benchbase
```

**Method 2 — Database files only (container stopped)**

```bash
export REPO=/path/to/benchbase
export DATA="$REPO/docker/data"
export BACKUP_DIR="$REPO/backups"
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)

cd "$REPO/docker"
docker compose stop benchbase

cp "$DATA/benchbase.db" "$BACKUP_DIR/benchbase.db.$STAMP"
[ -f "$DATA/benchbase.db-wal" ] && cp "$DATA/benchbase.db-wal" "$BACKUP_DIR/benchbase.db-wal.$STAMP"
[ -f "$DATA/benchbase.db-shm" ] && cp "$DATA/benchbase.db-shm" "$BACKUP_DIR/benchbase.db-shm.$STAMP"

docker compose start benchbase
```

**Portainer:** stop the `benchbase` container from the UI, run backup commands on the host, then start the container.

### Restore procedure

```bash
export REPO=/path/to/benchbase
export DATA="$REPO/docker/data"
export BACKUP=/path/to/benchbase-backup.tar.gz   # your archive

cd "$REPO/docker"
docker compose stop benchbase

# Full directory restore
rm -rf "$DATA"
mkdir -p "$DATA"
tar -xzf "$BACKUP" -C "$REPO/docker"

docker compose start benchbase
```

Or restore individual files into `$DATA/` while stopped (replace `benchbase.db`, `benchbase.db-wal`, `benchbase.db-shm`).

**Verification after restore**

```bash
sqlite3 "$DATA/benchbase.db" "SELECT COUNT(*) FROM runs;"
curl -fsS http://localhost:8000/api/benchmarks/runs | head -c 300
```

### Backup rules

1. **Stop the container** before file-level copies (avoids locked/partial WAL state).
2. Copy **all three** SQLite files if they exist: `benchbase.db`, `benchbase.db-wal`, `benchbase.db-shm`.
3. Store backups **outside** `docker/data/` (e.g. `$REPO/backups/`).
4. Removing a Portainer stack with **bind mounts** does not delete host `docker/data/` — but confirm mounts are bind paths, not anonymous volumes, before stack deletion.

---

## Phase 6 — Updates (preserve database)

```bash
export REPO=/path/to/benchbase
cd "$REPO/docker"

# Optional: backup first (see Phase 5)
docker compose build --no-cache
docker compose up -d
```

In Portainer: **Update the stack** → rebuild image → redeploy. Do **not** change `BENCHBASE_HOST_DATA` if you want to keep the same database.

---

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Models inactive / 401 | Set API key in Settings; use `host.docker.internal` for LiteLLM URL |
| `database is locked` | Only one container/CLI on `DATA`; restart container |
| Empty history after migrate | Confirm `benchbase.db` is in `docker/data/`, not repo root |
| Health check failing | Wait 40s start period; check container logs in Portainer |
| Permission errors on data | `chmod/chown` on `$REPO/docker/data` for container user |

---

## Quick reference — host paths

```
REPO/
  config/
    settings.yaml.example   # template (in git)
    settings.yaml           # local only (bind mount → /app/config)
  docker/
    data/                   # bind mount → /app/data
      benchbase.db
      benchbase.db-wal      # may exist (WAL mode)
      benchbase.db-shm      # may exist (WAL mode)
      run_logs/
  backups/                  # optional; not in git
```
