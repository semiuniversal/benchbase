"""lm-eval CLI entry point with BenchBase live sample logging."""

from __future__ import annotations

from benchbase.runners.lm_eval_log_patch import apply_lm_eval_log_patch

apply_lm_eval_log_patch()

from lm_eval.__main__ import cli_evaluate  # noqa: E402


if __name__ == "__main__":
    cli_evaluate()
