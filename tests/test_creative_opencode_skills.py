"""OpenCode skill corpus layout (ZooCode → OpenCode translation)."""

import re
from pathlib import Path

import pytest

from benchbase.creative.workspace import provision_attempt_workspace

SKILLS_ROOT = (
    Path(__file__).resolve().parents[1] / "corpus" / "creative" / "opencode" / "skills"
)
REQUIRED_SKILL_IDS = ("volcano-build", "creative-shell", "creative-browser-check")
FRONTMATTER = re.compile(r"^---\s*\n(.+?)\n---", re.DOTALL)


def _parse_skill_ids() -> list[str]:
    return sorted(p.parent.name for p in SKILLS_ROOT.glob("*/SKILL.md"))


@pytest.mark.parametrize("skill_id", REQUIRED_SKILL_IDS)
def test_skill_md_frontmatter(skill_id: str):
    path = SKILLS_ROOT / skill_id / "SKILL.md"
    assert path.is_file(), f"missing {path}"
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER.match(text)
    assert m, "SKILL.md needs YAML frontmatter"
    body = m.group(1)
    assert "name:" in body
    assert "description:" in body


def test_volcano_agent_references_skills():
    cfg = (
        Path(__file__).resolve().parents[1]
        / "corpus"
        / "creative"
        / "opencode"
        / "volcano-agent.jsonc"
    ).read_text(encoding="utf-8")
    assert ".opencode/skills" in cfg
    for skill_id in REQUIRED_SKILL_IDS:
        assert skill_id in cfg


def test_workspace_copies_opencode_skills(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BENCHBASE_DATA_DIR", str(tmp_path))
    from benchbase import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    root = provision_attempt_workspace("skill-copy", model_name="m1")
    for skill_id in REQUIRED_SKILL_IDS:
        assert (root / ".opencode" / "skills" / skill_id / "SKILL.md").is_file()
    assert (root / "project" / "BRIEF.md").is_file()
    assert set(_parse_skill_ids()) >= set(REQUIRED_SKILL_IDS)