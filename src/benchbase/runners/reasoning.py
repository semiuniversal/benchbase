"""Reasoning benchmark runner backed by lm-evaluation-harness."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from benchbase.config import load_settings
from benchbase.runners.run_metadata import is_full_benchmark, metadata_optional_int
from benchbase.db.models import Result, Run
from benchbase.runners.base import BenchmarkRunner
from benchbase.runners.registry import register_runner
from benchbase.run_controller import is_cancelled
from benchbase.runners.subprocess_utils import make_temp_dir, run_tool
from benchbase.run_log import RunLogManager, run_log_context


# Avoid the full `mmlu` group (50+ subtasks). One GSM8K + three MC probes.
DEFAULT_TASKS = [
    "gsm8k",
    "arc_easy",
    "hellaswag",
    "mmlu_high_school_mathematics",
]

# lm-eval tasks scored via generation (chat-completions API).
GENERATIVE_TASK_PREFIXES = ("gsm8k",)


@register_runner("reasoning")
class ReasoningRunner(BenchmarkRunner):
    """Invokes lm-evaluation-harness to run reasoning benchmarks."""

    async def run(self, run: Run, db: AsyncSession) -> None:
        settings = load_settings()
        model_name = run.model.name
        litellm_base = settings.litellm_base_url.rstrip("/")
        tmpdir = make_temp_dir("benchbase_reasoning_")

        suite_config = json.loads(run.suite.config_json) if run.suite.config_json else {}
        tasks = _normalize_tasks(suite_config.get("tasks", DEFAULT_TASKS))
        num_concurrent = suite_config.get("num_concurrent", 1)
        limit = metadata_optional_int(run, "limit", suite_config)
        tokenizer = suite_config.get("tokenizer", "gpt2")
        eos_string = suite_config.get("eos_string", "")

        env: dict[str, str] = {}
        if settings.litellm_api_key:
            env["OPENAI_API_KEY"] = settings.litellm_api_key

        gen_tasks = [t for t in tasks if _is_generative_task(t)]
        mc_tasks = [t for t in tasks if not _is_generative_task(t)]

        _log(run.id, f"Reasoning tasks: generative={gen_tasks}, loglikelihood={mc_tasks}")

        if limit is not None:
            _log(
                run.id,
                f"Sample limit {limit} per reasoning task "
                f"(~{limit * len(tasks)} API calls — not full-suite metrics).",
            )
        elif is_full_benchmark(run):
            _log(
                run.id,
                "Full reasoning benchmark — entire task datasets (10,000+ questions possible).",
            )

        results_data: dict[str, dict] = {}
        errors: list[str] = []

        logprobs_ok = True
        logprobs_detail = ""
        if mc_tasks:
            logprobs_ok, logprobs_detail = await _completions_logprobs_available(
                litellm_base, model_name, settings.litellm_api_key
            )
            if not logprobs_ok:
                _log(
                    run.id,
                    "Completions logprobs unavailable — "
                    f"{logprobs_detail}. "
                    f"Generative tasks will run; MC tasks ({', '.join(mc_tasks)}) will be skipped. "
                    "Enable logprobs on your LiteLLM/vLLM backend to score ARC/HellaSwag/MMLU.",
                )

        if gen_tasks:
            if is_cancelled(run.id):
                raise RuntimeError("cancelled")
            try:
                _log(run.id, "Starting generative phase (chat completions)…")
                chat_url = f"{litellm_base}/v1/chat/completions"
                results_data.update(
                    await self._invoke_lm_eval(
                        run_id=run.id,
                        tasks=gen_tasks,
                        model="local-chat-completions",
                        base_url=chat_url,
                        model_name=model_name,
                        num_concurrent=num_concurrent,
                        limit=limit,
                        apply_chat_template=True,
                        tokenizer=tokenizer,
                        eos_string=eos_string,
                        tmpdir=tmpdir,
                        env=env,
                        timeout=suite_config.get("timeout", 3600),
                        tag="generative",
                    )
                )
            except Exception as exc:
                errors.append(f"generative ({','.join(gen_tasks)}): {exc}")
                _log(run.id, f"Generative phase failed: {exc}")

        if mc_tasks:
            if is_cancelled(run.id):
                raise RuntimeError("cancelled")
            if not logprobs_ok:
                skip_msg = (
                    f"loglikelihood ({','.join(mc_tasks)}): skipped — {logprobs_detail}"
                )
                errors.append(skip_msg)
            else:
                try:
                    _log(run.id, "Starting multiple-choice phase (completions + logprobs)…")
                    completions_url = f"{litellm_base}/v1/completions"
                    results_data.update(
                        await self._invoke_lm_eval(
                            run_id=run.id,
                            tasks=mc_tasks,
                            model="local-completions",
                            base_url=completions_url,
                            model_name=model_name,
                            num_concurrent=num_concurrent,
                            limit=limit,
                            apply_chat_template=False,
                            tokenizer=tokenizer,
                            eos_string=None,
                            tmpdir=tmpdir,
                            env=env,
                            timeout=suite_config.get("timeout", 3600),
                            tag="loglikelihood",
                        )
                    )
                except Exception as exc:
                    errors.append(f"loglikelihood ({','.join(mc_tasks)}): {exc}")
                    _log(run.id, f"Multiple-choice phase failed: {exc}")

        if not results_data:
            raise RuntimeError(
                errors[0] if len(errors) == 1 else "; ".join(errors)
            )

        for task_name, task_results in results_data.items():
            score = (
                task_results.get("acc,none")
                or task_results.get("acc_norm,none")
                or task_results.get("exact_match,strict-match")
            )
            if score is None:
                for k, v in task_results.items():
                    if isinstance(v, (int, float)) and "stderr" not in k:
                        score = v
                        break

            score_pct = None
            if score is not None:
                score_pct = score * 100 if score <= 1.0 else score

            db.add(Result(
                run_id=run.id,
                task_name=f"reasoning:{task_name}",
                score=score_pct,
                metrics_json=json.dumps(task_results),
                raw_output_json=json.dumps(task_results),
            ))

        if errors:
            meta = {}
            if run.metadata_json:
                try:
                    meta = json.loads(run.metadata_json)
                except json.JSONDecodeError:
                    meta = {}
            meta["partial_errors"] = errors
            run.metadata_json = json.dumps(meta)
            _log(run.id, "Partial completion — some phases failed (see partial_errors).")

        await db.commit()
        shutil.rmtree(tmpdir, ignore_errors=True)

    async def _invoke_lm_eval(
        self,
        *,
        run_id: int,
        tasks: list[str],
        model: str,
        base_url: str,
        model_name: str,
        num_concurrent: int,
        limit: int | None,
        apply_chat_template: bool,
        tokenizer: str,
        eos_string: str | None,
        tmpdir: Path,
        env: dict[str, str],
        timeout: int,
        tag: str,
    ) -> dict[str, dict]:
        model_args = (
            f"model={model_name},"
            f"base_url={base_url},"
            f"num_concurrent={num_concurrent},"
            f"tokenizer_backend=huggingface,"
            f"tokenizer={tokenizer},"
            f"tokenized_requests=False"
        )
        if eos_string:
            model_args += f",eos_string={eos_string}"

        out_dir = tmpdir / tag
        out_dir.mkdir(parents=True, exist_ok=True)

        args = [
            "lm-eval", "run",
            "--model", model,
            "--model_args", model_args,
            "--tasks", ",".join(tasks),
            "--output_path", str(out_dir),
            "--log_samples",
        ]
        if apply_chat_template:
            args.append("--apply_chat_template")
        if limit is not None:
            args.extend(["--limit", str(limit)])

        proc = await run_tool(args, timeout=timeout, env=env, run_id=run_id)

        if proc.timed_out:
            raise RuntimeError(f"lm-eval timed out ({tag})")
        if proc.cancelled:
            raise RuntimeError("cancelled")
        if proc.returncode != 0:
            tail = f"{proc.stdout}\n{proc.stderr}"[-2000:]
            raise RuntimeError(
                f"lm-eval {tag} failed (exit {proc.returncode}): {tail}"
            )

        return _find_results(out_dir)

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "Reasoning Benchmark",
            "category": "reasoning",
            "description": (
                "lm-evaluation-harness: GSM8K via chat completions; "
                "ARC/HellaSwag/MMLU via completions+logprobs when the inference "
                "backend returns logprobs (skipped otherwise)."
            ),
        }


def _normalize_tasks(tasks: list[str]) -> list[str]:
    """Replace the full mmlu task group with a single representative subject."""
    if "mmlu" not in tasks:
        return tasks
    out = [t for t in tasks if t != "mmlu"]
    if "mmlu_high_school_mathematics" not in out:
        out.append("mmlu_high_school_mathematics")
    return out


def _is_generative_task(task_name: str) -> bool:
    return any(task_name.startswith(prefix) for prefix in GENERATIVE_TASK_PREFIXES)


def _log(run_id: int, message: str) -> None:
    if run_log_context.get() == run_id:
        RunLogManager.log(run_id, message)


async def _completions_logprobs_available(
    litellm_base: str,
    model_name: str,
    api_key: str | None,
) -> tuple[bool, str]:
    """Probe whether /v1/completions returns token logprobs (required for MC tasks)."""
    url = f"{litellm_base.rstrip('/')}/v1/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model_name,
        "prompt": "logprobs probe",
        "max_tokens": 1,
        "temperature": 0,
        "logprobs": 1,
        "echo": True,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                return False, f"completions HTTP {resp.status_code}"
            choices = resp.json().get("choices") or []
            if not choices:
                return False, "completions returned no choices"
            logprobs = choices[0].get("logprobs")
            if not logprobs or logprobs.get("token_logprobs") is None:
                return False, "completions returned null logprobs"
            return True, ""
    except Exception as exc:
        return False, str(exc)


def _find_results(output_dir: Path) -> dict[str, dict]:
    """Parse lm-eval output (results.json or results_<timestamp>.json per model subdir)."""
    results: dict[str, dict] = {}
    candidates: list[Path] = []

    for path in output_dir.rglob("*.json"):
        name = path.name
        if name == "results.json" or (
            name.startswith("results_") and name.endswith(".json")
        ):
            candidates.append(path)

    # lm-eval writes one aggregated file per model subdir; prefer the newest.
    newest_by_dir: dict[Path, Path] = {}
    for path in candidates:
        parent = path.parent
        prev = newest_by_dir.get(parent)
        if prev is None or path.stat().st_mtime > prev.stat().st_mtime:
            newest_by_dir[parent] = path

    for results_json in newest_by_dir.values():
        try:
            data = json.loads(results_json.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        task_results = data.get("results", {})
        for task_name, metrics in task_results.items():
            if isinstance(metrics, dict):
                results[task_name] = metrics

    return results
