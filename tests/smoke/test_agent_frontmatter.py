from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXPECTED_AGENTS = ["opn-planner", "opn-diag"]

FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def test_all_agents_exist_with_valid_frontmatter() -> None:
    agents_dir = REPO_ROOT / "agents"
    for name in EXPECTED_AGENTS:
        path = agents_dir / f"{name}.md"
        assert path.exists(), f"Missing agent: {name}"
        content = path.read_text()
        m = FRONTMATTER.match(content)
        assert m is not None, f"{name}: missing YAML frontmatter"
        front = m.group(1)
        assert f"name: {name}" in front, f"{name}: name mismatch"
        assert "description:" in front, f"{name}: missing description"
