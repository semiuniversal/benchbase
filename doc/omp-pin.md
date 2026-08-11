# Oh My Pi (OMP) — pinned BenchBase resource

BenchBase drives **Oh My Pi** as a fixed diagnostic harness for the agentic suite.
We do **not** develop OMP here; we pin a release and treat upgrades as
`harness_version` changes (new experiment).

## Pin

| Field | Value |
|-------|--------|
| Path | [`third_party/omp`](../third_party/omp) (git submodule; source of truth for SHA) |
| Version file | [`third_party/omp.VERSION`](../third_party/omp.VERSION) |
| Upstream | https://github.com/can1357/oh-my-pi |
| Current pin | **v9.8.0** (`a37b5f4b988cd44ec6262b37cd9c5be50327739a`) |
| Runtime CLI | host Bun global `@oh-my-pi/pi-coding-agent@9.8.0` → `~/.bun/bin/omp` |

```bash
git submodule update --init --recursive third_party/omp
cd third_party/omp && git checkout "$(head -1 ../omp.VERSION)"
```

## Install CLI (runner host)

OMP is a Bun project. On the host that runs agentic benchmarks:

```bash
# Bun (npm works without system unzip):
npm install -g bun

# Pin-matching CLI (includes prebuilt natives):
bun install -g @oh-my-pi/pi-coding-agent@9.8.0
omp --help
```

Configure providers in `~/.omp/agent/models.yml` (preferred; OMP ignores
`models.json` when yml exists). LiteLLM for local UUTs; `openrouter` for the
instrument model `deepseek/deepseek-v4-flash-0731` with `apiKey: OPENROUTER_API_KEY`.
See [`agentic-instrument.md`](agentic-instrument.md).

## Docker / BenchBase container

`docker/docker-compose.yml` mounts the host Bun install and OMP config:

| Host | Container |
|------|-----------|
| `~/.bun` | `/opt/bun` (ro) |
| `~/.omp` | `/root/.omp` |

Env: `BENCHBASE_OMP_BIN=/opt/bun/bin/omp`, `BENCHBASE_OMP_PROVIDER` (`litellm` or
`openrouter`), `PATH` includes `/opt/bun/bin`.

- Local UUT path: `OPENAI_API_KEY` for LiteLLM (`sk-local-litellm`).
- Instrument path: `OPENROUTER_API_KEY` + provider `openrouter` in
  `~/.omp/agent/models.json` (model `deepseek/deepseek-v4-flash-0731`). See
  [`agentic-instrument.md`](agentic-instrument.md).

After installing Bun/OMP on the host, recreate the container so mounts apply.

Inference stays sole-tenant on the Spark; OMP runs in the BenchBase API container
(or a future dedicated agentic worker). See
[`agentic-sole-tenancy.md`](agentic-sole-tenancy.md).

## Upgrading the pin

1. Update `third_party/omp.VERSION` and submodule tag
2. `bun install -g @oh-my-pi/pi-coding-agent@<same-version>`
3. Re-run the ledger spike (`doc/omp-ledger-spike.md`) before trusting scores
4. Bump recorded `harness_version` on all new agentic runs
