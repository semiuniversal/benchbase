"""Attempt workspace layout (spec §11.5)."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from benchbase.config import DATA_DIR

REPO_ROOT = Path(__file__).resolve().parents[3]
OPENCODE_TEMPLATE = REPO_ROOT / "corpus" / "creative" / "opencode" / "volcano-agent.jsonc"
OPENCODE_SKILLS = REPO_ROOT / "corpus" / "creative" / "opencode" / "skills"
CHALLENGE_PROMPT = REPO_ROOT / "corpus" / "creative" / "volcano-skunk-v1" / "prompt.txt"
CHALLENGE_ID = "volcano-skunk-v1"


def attempt_root(attempt_uuid: str, challenge_id: str = CHALLENGE_ID) -> Path:
    return DATA_DIR / "creative" / challenge_id / attempt_uuid


def provision_attempt_workspace(
    attempt_uuid: str,
    *,
    model_name: str,
    challenge_id: str = CHALLENGE_ID,
    harness: str = "mock",
) -> Path:
    root = attempt_root(attempt_uuid, challenge_id)
    project = root / "project"
    for rel in ("project", "logs", "build", "evidence", "media", "session"):
        (root / rel).mkdir(parents=True, exist_ok=True)

    if OPENCODE_TEMPLATE.is_file():
        shutil.copy2(OPENCODE_TEMPLATE, root / "opencode.jsonc")

    if OPENCODE_SKILLS.is_dir():
        dest_skills = root / ".opencode" / "skills"
        shutil.copytree(OPENCODE_SKILLS, dest_skills, dirs_exist_ok=True)

    if CHALLENGE_PROMPT.is_file():
        shutil.copy2(CHALLENGE_PROMPT, project / "BRIEF.md")

    manifest = {
        "attempt_uuid": attempt_uuid,
        "challenge_id": challenge_id,
        "model_name": model_name,
        "harness": harness,
        "created_at": datetime.now(UTC).isoformat(),
        "opencode_template": str(OPENCODE_TEMPLATE.name),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (root / "logs" / "events.jsonl").touch()
    return root