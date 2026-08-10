# Oh My Pi (OMP) — pinned BenchBase resource

BenchBase drives **Oh My Pi** as a fixed diagnostic harness for the agentic suite.
We do **not** develop OMP here; we pin a release and treat upgrades as
`harness_version` changes (new experiment).

## Pin

| Field | Value |
|-------|--------|
| Path | [`third_party/omp`](../third_party/omp) (git submodule) |
| Version file | [`third_party/omp.VERSION`](../third_party/omp.VERSION) |
| Upstream | https://github.com/can1357/oh-my-pi |
| Current pin | **v9.8.0** (`a37b5f4b988cd44ec6262b37cd9c5be50327739a`) |

```bash
git submodule update --init --recursive third_party/omp
cd third_party/omp && git checkout "$(head -1 ../omp.VERSION)"
```

## Install CLI (runner host)

OMP is a Bun project. On the host that runs agentic benchmarks (not necessarily
inside the BenchBase API container):

```bash
# Install Bun if needed: https://bun.sh
curl -fsSL https://bun.sh/install | bash

cd third_party/omp
bun install
# CLI entry — see package.json scripts; typically:
bun run omp --help
# or after linking:
# bun link && omp --help
```

Point OMP at BenchBase’s LiteLLM profile (same models as quality suites), e.g.
OpenAI-compatible base URL `http://<litellm>:4000/v1` and the local API key from
`settings.yaml`.

## Docker note

The default `benchbase:local` image does **not** yet bundle Bun/OMP. Agentic
runs expect OMP on the **runner host** (or a future dedicated agentic worker
image) while inference stays sole-tenant on the Spark. See sole-tenancy rules in
[`benchbase-agentic-extension-spec.md`](benchbase-agentic-extension-spec.md).

## Upgrading the pin

1. `cd third_party/omp && git fetch --tags && git checkout <new-tag>`
2. Update `third_party/omp.VERSION`
3. Re-run the ledger spike (`doc/omp-ledger-spike.md`) before trusting scores
4. Bump recorded `harness_version` on all new agentic runs
