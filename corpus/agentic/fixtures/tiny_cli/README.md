# tiny_cli fixture

Purpose-built BenchBase agentic fixture (not a popular OSS clone).

Seams:
- `src/greet.py` — greeting string
- `src/mathutil.py` — `clamp_index` off-by-one
- `src/cli.py` — argparse flags (`--verbose` missing)
- `config.toml` — defaults

Instantiation: copy tree; verify `state.hash`. Never `git clean` a dirty workspace.
