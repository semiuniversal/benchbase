"""Agentic / finalist suite runner (OMP harness, T_eff persistence)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from benchbase.agentic.ledger import AttemptLedger
from benchbase.agentic.metrics import (
    compute_task_metrics,
    geometric_mean_teff_ratio,
    task_metrics_to_dict,
)
from benchbase.agentic.omp_driver import OmpDriver
from benchbase.agentic.tasks import load_tasks, suite_manifest
from benchbase.agentic.workspace import destroy_workspace, instantiate_fixture
from benchbase.db.models import Model, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.progress_log import AxisProgressLog
from benchbase.runners.quality_common import persist_axis_result
from benchbase.runners.registry import register_runner
from benchbase.run_log import RunLogManager

OMP_VERSION_FILE = Path(__file__).resolve().parents[3] / "third_party" / "omp.VERSION"
FIXTURE_TRANSCRIPT = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "omp_sessions" / "trivial_edit.jsonl"
)


def _harness_version() -> str:
    if OMP_VERSION_FILE.exists():
        lines = OMP_VERSION_FILE.read_text(encoding="utf-8").strip().splitlines()
        return lines[0] if lines else "unknown"
    return "unknown"


def _run_config(run: Run) -> dict[str, Any]:
    raw = {}
    if run.config_json:
        try:
            raw = json.loads(run.config_json)
        except json.JSONDecodeError:
            raw = {}
    if run.metadata_json:
        try:
            meta = json.loads(run.metadata_json)
            if isinstance(meta, dict):
                raw = {**raw, **meta}
        except json.JSONDecodeError:
            pass
    return raw


def _run_checker(workspace: Path, check_script: Path) -> tuple[bool, str]:
    env = os.environ.copy()
    env["AGENTIC_WORKSPACE"] = str(workspace)
    proc = subprocess.run(
        ["bash", str(check_script)],
        cwd=str(workspace),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


def _prepare_injection(task_id: str, workspace: Path) -> None:
    if task_id == "fail-once-write":
        (workspace / ".fail_once_lock").write_text("1\n", encoding="utf-8")


@register_runner("agentic")
class AgenticRunner(BenchmarkRunner):
    async def run(self, run: Run, db: AsyncSession) -> None:
        run_db = await db.get(
            Run, run.id, options=[selectinload(Run.model), selectinload(Run.suite)]
        )
        model: Model = run_db.model
        cfg = _run_config(run_db)
        suite_version = str(
            cfg.get("suite_version")
            or (run_db.suite.suite_version if run_db.suite else "mvp")
        )
        # Map suite_version tags: v1-mvp -> mvp, v1-headline -> headline
        suite_key = suite_version
        if suite_version in {"v1", "mvp", "v1-mvp"}:
            suite_key = "mvp"
        elif suite_version in {"headline", "v1-headline"}:
            suite_key = "headline"

        n_seeds = int(cfg.get("n_seeds") or suite_manifest(suite_key).get("default_seeds") or 3)
        task_ids = cfg.get("task_ids")
        if task_ids is not None and not isinstance(task_ids, list):
            task_ids = None
        mock = bool(cfg.get("mock") or cfg.get("use_fixture_transcript"))
        omp_bin = cfg.get("omp_bin") or os.environ.get("BENCHBASE_OMP_BIN") or "omp"

        tasks = load_tasks(suite_key, task_ids=task_ids)
        if not tasks:
            raise RuntimeError(f"No agentic tasks for suite={suite_key}")

        total_attempts = sum(n_seeds for _ in tasks)
        progress = AxisProgressLog(
            title=run_db.suite.name if run_db.suite else "agentic",
            total=total_attempts,
            tier="finalist",
        )
        RunLogManager.log(
            run_db.id,
            f"Agentic suite={suite_key} tasks={len(tasks)} n_seeds={n_seeds} "
            f"harness={_harness_version()} mock={mock}\n",
        )

        all_item_rows: list[dict[str, Any]] = []
        per_task_metrics: list[dict[str, Any]] = []
        task_metric_objs = []

        for task in tasks:
            ledgers: list[AttemptLedger] = []
            for seed in range(n_seeds):
                ws = instantiate_fixture(task.fixture)
                try:
                    _prepare_injection(task.task_id, ws)
                    timeout = min(task.timeout_s, task.hard_cap_s)
                    if mock:
                        driver = OmpDriver(
                            fixture_transcript=FIXTURE_TRANSCRIPT,
                            cwd=ws,
                            timeout_s=timeout,
                        )
                        ledger = driver.run_attempt(task.instruction)
                        if task.expected == "unsolvable":
                            (ws / "ABSTAINED").write_text(
                                "missing credential — cannot proceed\n", encoding="utf-8"
                            )
                            ledger.abstained = True
                        elif task.failure_injection and task.task_id == "fail-once-write":
                            (ws / "out.txt").write_text("recovered\n", encoding="utf-8")
                            (ws / ".fail_once_lock").unlink(missing_ok=True)
                        elif task.task_id == "greet-welcome":
                            greet = ws / "src" / "greet.py"
                            greet.write_text(
                                greet.read_text().replace("Hello", "Welcome"),
                                encoding="utf-8",
                            )
                    else:
                        driver = OmpDriver(
                            omp_bin=str(omp_bin),
                            cwd=ws,
                            model=model.name,
                            timeout_s=timeout,
                        )
                        ledger = driver.run_attempt(task.instruction)

                    ok, check_out = _run_checker(ws, task.check_script)
                    ledger.resolved = ok
                    if task.expected == "unsolvable":
                        ledger.abstained = (ws / "ABSTAINED").exists()
                    ledgers.append(ledger)
                    row = {
                        "item_id": f"{task.task_id}:seed{seed}",
                        "passed": ok,
                        "raw_answer": check_out[:2000] if check_out else None,
                        "latency_ms": ledger.wall_seconds * 1000.0,
                        "detail": ledger.to_dict(),
                        "reason": None if ok else "checker_failed",
                    }
                    all_item_rows.append(row)
                    progress.record(row, sample_text=f"{task.task_id} seed={seed}")
                    RunLogManager.log(
                        run_db.id,
                        f"  {task.task_id} seed={seed} resolved={ok} "
                        f"wall={ledger.wall_seconds:.1f}s tools={ledger.tool_calls}\n",
                    )
                finally:
                    destroy_workspace(ws)

            tm = compute_task_metrics(
                task.task_id,
                ledgers,
                expected=task.expected,
                failure_injection=task.failure_injection,
            )
            task_metric_objs.append(tm)
            per_task_metrics.append(task_metrics_to_dict(tm))

        geo = geometric_mean_teff_ratio(task_metric_objs, task_metric_objs)
        package_hash = cfg.get("package_hash") or "placeholder-until-estimator-store"

        run_db.config_json = json.dumps(
            {
                **cfg,
                "harness_version": _harness_version(),
                "suite_version": suite_key,
                "n_seeds": n_seeds,
                "package_hash": package_hash,
                "litellm_profile": cfg.get("litellm_profile") or model.endpoint_url,
                "concurrency": 1,
                "sole_tenancy": True,
            }
        )
        await db.flush()

        metrics = {
            "suite": suite_key,
            "harness_version": _harness_version(),
            "n_seeds": n_seeds,
            "per_task": per_task_metrics,
            "geo_mean_teff_vs_self": geo.get("geo_mean"),
            "geo_mean_detail": geo,
            "package_hash": package_hash,
            "pass_at_1_approx": (
                sum(1 for r in all_item_rows if r.get("passed")) / max(len(all_item_rows), 1)
            ),
        }
        result = await persist_axis_result(
            db,
            run_db,
            task_name=f"agentic:{suite_key}",
            item_rows=all_item_rows,
            primary_method="teff",
            metrics=metrics,
        )
        progress.finish(result.score)

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "agentic",
            "category": "agentic",
            "axis": "agentic",
            "description": "Finalist agentic suite via pinned Oh My Pi (T_eff).",
        }
