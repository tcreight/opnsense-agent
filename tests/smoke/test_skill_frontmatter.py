from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXPECTED_SKILLS = [
    "opn-safety",
    "opn-planning",
    "opn-interfaces",
    "opn-vlans",
    "opn-dhcp",
    "opn-troubleshooting",
]

FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def test_all_v1_skills_exist_with_valid_frontmatter() -> None:
    skills_dir = REPO_ROOT / "skills"
    for name in EXPECTED_SKILLS:
        path = skills_dir / name / "SKILL.md"
        assert path.exists(), f"Missing skill: {name}"
        content = path.read_text()
        m = FRONTMATTER.match(content)
        assert m is not None, f"{name}: missing YAML frontmatter"
        front = m.group(1)
        assert f"name: {name}" in front, f"{name}: name mismatch"
        assert "description:" in front, f"{name}: missing description"
