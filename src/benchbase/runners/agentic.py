"""Agentic / finalist suite runner (OMP harness, T_eff persistence)."""

from __future__ import annotations

import asyncio
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
from benchbase.agentic.session_store import (
    AttemptEventBus,
    clear_current,
    item_id as make_item_id,
    transcript_abspath,
    transcript_relpath,
    write_current,
)
from benchbase.agentic.tasks import load_tasks, suite_manifest
from benchbase.agentic.workspace import destroy_workspace, instantiate_fixture
from benchbase.config import load_settings
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
        omp_provider = (
            cfg.get("omp_provider")
            or os.environ.get("BENCHBASE_OMP_PROVIDER")
            or "litellm"
        )
        settings = load_settings()
        openrouter_key = (
            str(cfg.get("openrouter_api_key") or "")
            or os.environ.get("OPENROUTER_API_KEY")
            or ""
        ).strip()
        litellm_key = (
            settings.litellm_api_key or os.environ.get("OPENAI_API_KEY", "") or ""
        ).strip()
        # Instrument path (OpenRouter): never reuse a local UUT key for OMP.
        if str(omp_provider) == "openrouter":
            omp_api_key = openrouter_key
            if not omp_api_key:
                raise RuntimeError(
                    "omp_provider=openrouter requires OPENROUTER_API_KEY "
                    "(instrument LLM — see doc/agentic-instrument.md)"
                )
        else:
            omp_api_key = litellm_key
        omp_model = str(
            cfg.get("omp_model")
            or os.environ.get("OPENROUTER_MODEL")
            or model.name
        )
        if str(omp_provider) == "openrouter" and not cfg.get("omp_model"):
            # Prefer explicit instrument slug when provider is openrouter.
            omp_model = str(
                os.environ.get("OPENROUTER_MODEL")
                or "deepseek/deepseek-v4-flash-0731"
            )
        omp_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", "/root"),
            "OPENAI_API_KEY": omp_api_key,
            "OPENROUTER_API_KEY": openrouter_key or omp_api_key,
            "OMP_PROVIDER": str(omp_provider),
        }
        # Ensure bun/omp dir is on PATH when BENCHBASE_OMP_BIN is an absolute path.
        omp_dir = str(Path(omp_bin).resolve().parent) if Path(omp_bin).name != omp_bin else ""
        if omp_dir and omp_dir not in omp_env["PATH"].split(":"):
            omp_env["PATH"] = f"{omp_dir}:{omp_env['PATH']}"

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
            f"harness={_harness_version()} mock={mock} "
            f"provider={omp_provider} model={omp_model}\n",
        )

        all_item_rows: list[dict[str, Any]] = []
        per_task_metrics: list[dict[str, Any]] = []
        task_metric_objs = []

        for task in tasks:
            ledgers: list[AttemptLedger] = []
            for seed in range(n_seeds):
                attempt_key = make_item_id(task.task_id, seed)
                rel = transcript_relpath(run_db.id, task.task_id, seed)
                abs_transcript = transcript_abspath(run_db.id, task.task_id, seed)
                write_current(
                    run_db.id,
                    item_id_value=attempt_key,
                    task_id=task.task_id,
                    seed=seed,
                    fixture=task.fixture,
                    instruction=task.instruction,
                )
                bus = AttemptEventBus.open(run_db.id, attempt_key)
                try:
                    bus.bind_loop(asyncio.get_running_loop())
                except RuntimeError:
                    pass
                # Fixture/OMP/checker are sync and long-running — keep them off the
                # event loop or the whole API (including Finalist start) freezes.
                ws = await asyncio.to_thread(instantiate_fixture, task.fixture)
                try:
                    await asyncio.to_thread(_prepare_injection, task.task_id, ws)
                    timeout = min(task.timeout_s, task.hard_cap_s)
                    if mock:
                        driver = OmpDriver(
                            fixture_transcript=FIXTURE_TRANSCRIPT,
                            cwd=ws,
                            timeout_s=timeout,
                            transcript_path=abs_transcript,
                            transcript_relpath=rel,
                            event_bus=bus,
                        )
                        ledger = await asyncio.to_thread(
                            driver.run_attempt, task.instruction
                        )
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
                            model=omp_model,
                            provider=str(omp_provider),
                            timeout_s=timeout,
                            env=omp_env,
                            transcript_path=abs_transcript,
                            transcript_relpath=rel,
                            event_bus=bus,
                        )
                        ledger = await asyncio.to_thread(
                            driver.run_attempt, task.instruction
                        )

                    ok, check_out = await asyncio.to_thread(
                        _run_checker, ws, task.check_script
                    )
                    ledger.resolved = ok
                    ledger.transcript_path = rel
                    if task.expected == "unsolvable":
                        ledger.abstained = (ws / "ABSTAINED").exists()
                    ledgers.append(ledger)
                    detail = ledger.to_dict()
                    detail["fixture"] = task.fixture
                    detail["instruction"] = task.instruction
                    row = {
                        "item_id": attempt_key,
                        "passed": ok,
                        "raw_answer": check_out[:2000] if check_out else None,
                        "latency_ms": ledger.wall_seconds * 1000.0,
                        "detail": detail,
                        "reason": None if ok else "checker_failed",
                    }
                    all_item_rows.append(row)
                    progress.record(row, sample_text=f"{task.task_id} seed={seed}")
                    RunLogManager.log(
                        run_db.id,
                        f"  {task.task_id} seed={seed} resolved={ok} "
                        f"wall={ledger.wall_seconds:.1f}s tools={ledger.tool_calls}\n",
                    )
                    # Release the event loop between attempts so status/UI stay live.
                    await asyncio.sleep(0)
                finally:
                    AttemptEventBus.close(run_db.id, attempt_key)
                    await asyncio.to_thread(destroy_workspace, ws)

            tm = compute_task_metrics(
                task.task_id,
                ledgers,
                expected=task.expected,
                failure_injection=task.failure_injection,
            )
            task_metric_objs.append(tm)
            per_task_metrics.append(task_metrics_to_dict(tm))

        clear_current(run_db.id)
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
                "omp_provider": str(omp_provider),
                "omp_model": omp_model,
                "concurrency": 1,
                "sole_tenancy": True,
            }
        )
        await db.flush()

        n_passed = sum(1 for r in all_item_rows if r.get("passed"))
        n_attempts = len(all_item_rows)
        tool_vals = [int(r.get("detail", {}).get("tool_calls") or 0) for r in all_item_rows]
        turn_vals = [int(r.get("detail", {}).get("turns") or 0) for r in all_item_rows]
        metrics = {
            "suite": suite_key,
            "harness_version": _harness_version(),
            "n_seeds": n_seeds,
            "omp_provider": str(omp_provider),
            "omp_model": omp_model,
            "per_task": per_task_metrics,
            "geo_mean_teff_vs_self": geo.get("geo_mean"),
            "geo_mean_detail": geo,
            "package_hash": package_hash,
            "n_passed": n_passed,
            "n_attempts": n_attempts,
            "pass_at_1_approx": n_passed / max(n_attempts, 1),
            "mean_tool_calls": (sum(tool_vals) / max(len(tool_vals), 1)),
            "mean_turns": (sum(turn_vals) / max(len(turn_vals), 1)),
            "display": (
                f"Finalist · Agentic · {suite_key} · OMP {_harness_version()} · "
                f"{n_passed}/{n_attempts} pass · "
                f"mean_tools={sum(tool_vals)/max(len(tool_vals),1):.1f} · "
                f"{omp_provider}/{omp_model}"
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
