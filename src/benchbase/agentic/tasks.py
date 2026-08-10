"""Load agentic task definitions from corpus/agentic/tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from benchbase.agentic.workspace import AGENTIC_ROOT

TASKS_ROOT = AGENTIC_ROOT / "tasks"


@dataclass
class AgenticTask:
    task_id: str
    title: str
    instruction: str
    fixture: str
    timeout_s: int = 300
    seeds: int = 3
    expected: str = "solvable"  # solvable | unsolvable
    failure_injection: bool = False
    category: str = "edit"
    check_script: Path = field(default_factory=Path)
    prompts_dir: Path | None = None
    path: Path = field(default_factory=Path)
    suite: str = "mvp"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def hard_cap_s(self) -> int:
        return min(int(self.raw.get("hard_cap_s") or 480), 480)


def _parse_task_dir(task_dir: Path, suite: str) -> AgenticTask:
    yaml_path = task_dir / "task.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    check = task_dir / "check.sh"
    if not check.exists():
        raise FileNotFoundError(f"Missing check.sh in {task_dir}")
    prompts = task_dir / "prompts"
    return AgenticTask(
        task_id=str(data["id"]),
        title=str(data.get("title") or data["id"]),
        instruction=str(data["instruction"]),
        fixture=str(data["fixture"]),
        timeout_s=int(data.get("timeout_s") or data.get("timeout") or 300),
        seeds=int(data.get("seeds") or 3),
        expected=str(data.get("expected") or "solvable"),
        failure_injection=bool(data.get("failure_injection") or False),
        category=str(data.get("category") or "edit"),
        check_script=check,
        prompts_dir=prompts if prompts.is_dir() else None,
        path=task_dir,
        suite=suite,
        raw=data,
    )


def list_task_ids(suite: str = "mvp") -> list[str]:
    root = TASKS_ROOT / suite
    if not root.is_dir():
        return []
    ids = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "task.yaml").exists():
            data = yaml.safe_load((d / "task.yaml").read_text(encoding="utf-8")) or {}
            ids.append(str(data.get("id") or d.name))
    return ids


def load_tasks(
    suite: str = "mvp",
    *,
    task_ids: list[str] | None = None,
) -> list[AgenticTask]:
    root = TASKS_ROOT / suite
    if not root.is_dir():
        raise FileNotFoundError(f"Agentic suite not found: {root}")
    tasks: list[AgenticTask] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not (d / "task.yaml").exists():
            continue
        t = _parse_task_dir(d, suite)
        if task_ids is not None and t.task_id not in task_ids:
            continue
        tasks.append(t)
    return tasks


def suite_manifest(suite: str = "mvp") -> dict[str, Any]:
    path = TASKS_ROOT / suite / "SUITE.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    tasks = load_tasks(suite)
    return {
        "suite": suite,
        "n_tasks": len(tasks),
        "task_ids": [t.task_id for t in tasks],
        "default_seeds": 3 if suite == "mvp" else 5,
    }
