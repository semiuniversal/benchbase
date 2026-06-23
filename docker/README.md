# BenchBase Docker & Portainer

Run BenchBase as a container with **host bind mounts** for configuration and data. The SQLite database lives only on the mounted data volume — it is not stored inside the image.

## What gets persisted

| Host path (default) | Container path | Contents |
|---------------------|----------------|----------|
| `docker/data/` | `/app/data` | `benchbase.db`, `benchbase.db-wal`, `benchbase.db-shm`, `run_logs/`, `.benchbase-server.json` |
| `config/` (repo root) | `/app/config` | `settings.yaml` (copy from `settings.yaml.example`; LiteLLM URL, API key, sample sizes) |

The image does **not** contain your database. Rebuilding or replacing the container keeps data if the bind mounts are unchanged.

## Before first deploy — migrate existing CLI data

If you used `uv run benchbase serve` on the host, your database may be at the **repo root** (`benchbase.db`, `run_logs/`). Move it into the Docker data directory **once**, before starting the container:

```bash
cd /path/to/benchbase
mkdir -p docker/data
# Stop any local benchbase serve first.
[ -f benchbase.db ] && mv benchbase.db docker/data/
[ -f benchbase.db-wal ] && mv benchbase.db-wal docker/data/
[ -f benchbase.db-shm ] && mv benchbase.db-shm docker/data/
[ -d run_logs ] && mv run_logs docker/data/
```

**Do not** run CLI `benchbase serve` and Docker against the same `benchbase.db` at the same time.

## Quick start (CLI)

```bash
cd /path/to/benchbase/docker
cp .env.example .env
# Edit .env — set BENCHBASE_HOST_DATA and BENCHBASE_HOST_CONFIG to absolute paths.
mkdir -p "${BENCHBASE_HOST_DATA:-./data}"
docker compose up --build -d
```

Open **http://localhost:8000** (or your `BENCHBASE_PORT`).

MCP: **http://localhost:8000/mcp**

## Portainer deployment

### 1. Prepare directories on the host

On the machine where Portainer runs (same host as the bind mounts):

```bash
export REPO=/path/to/benchbase   # your clone path
mkdir -p "$REPO/docker/data"
cp -n "$REPO/config/settings.yaml.example" "$REPO/config/settings.yaml"
# Edit settings.yaml (LiteLLM URL, API key). Migrate existing DB if needed (see above).
```

### 2. Create a Stack

1. Portainer → **Stacks** → **Add stack**
2. Name: `benchbase`
3. **Build method:** Web editor **or** Repository (if Portainer can build from git)
4. Paste the contents of [`docker-compose.yml`](docker-compose.yml) (this file’s sibling in `docker/`)

### 3. Environment variables (Stack → Environment variables)

Set **absolute** host paths (Portainer does not resolve `../` reliably):

| Variable | Example | Purpose |
|----------|---------|---------|
| `BENCHBASE_HOST_DATA` | `/path/to/benchbase/docker/data` | Database and run logs |
| `BENCHBASE_HOST_CONFIG` | `/path/to/benchbase/config` | `settings.yaml` |
| `BENCHBASE_PORT` | `8000` | Host port published to the UI |

### 4. Build configuration

- **Context:** repository root (`benchbase/`, parent of `docker/`)
- **Dockerfile:** `docker/Dockerfile`

In Portainer’s stack editor when using git:

- Compose path: `docker/docker-compose.yml`
- Enable **Pull & rebuild** when you update the repo

If Portainer cannot build from git, build on the host and push to a registry, or use Portainer’s “build” option with upload.

### 5. Deploy

Deploy the stack. Wait for the health check to pass (Settings API on port 8000).

### 6. LiteLLM from inside the container

`localhost:4000` in `settings.yaml` points at the **container**, not your host. Use one of:

- `http://host.docker.internal:4000` (enabled via `extra_hosts` in compose)
- `http://<host-LAN-IP>:4000`
- `http://<litellm-service-name>:4000` if LiteLLM is another container on the same Docker network

Set this in **Settings** in the UI or in mounted `config/settings.yaml`, then save.

### 7. Updates (safe for the database)

```bash
cd /path/to/benchbase/docker
docker compose pull    # if using a registry image
docker compose build --no-cache
docker compose up -d
```

Or in Portainer: **Update the stack** → rebuild image → redeploy.

**Volumes are not removed** on stack update if bind mount paths stay the same.

## Database safety rules

1. **One writer** — Only one BenchBase container (or one CLI process) per data directory.
2. **Never mount `/app/data` read-only** — SQLite needs write access and WAL sidecar files.
3. **Backups** — Stop the container, then copy the whole data directory:

   ```bash
   docker compose stop
   tar -czf benchbase-backup-$(date +%Y%m%d).tar.gz -C /path/to/benchbase/docker data
   docker compose start
   ```

   Or copy `benchbase.db` + `benchbase.db-wal` + `benchbase.db-shm` together while stopped.

4. **Do not** delete `docker/data/` when removing a stack if you use bind mounts — Portainer “remove stack” does not delete bind mount host files, but confirm volumes are bind mounts, not anonymous volumes.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Empty UI / no models | Set LiteLLM URL to `host.docker.internal` and save API key in Settings |
| `database is locked` | Ensure only one container uses the data dir; restart container |
| Health check failing | Wait for `start_period` (40s); check logs in Portainer |
| Permission errors on data dir | `chown` data dir to UID the container uses, or run with matching user |

## Files in this directory

- `Dockerfile` — multi-stage build (frontend + Python)
- `docker-compose.yml` — service definition for CLI and Portainer
- `.env.example` — template for host paths
