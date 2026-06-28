from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXPECTED_COMMANDS = [
    "opn-plan",
    "opn-apply",
    "opn-status",
    "opn-backup",
    "opn-rollback",
    "opn-diag",
]

FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def test_all_commands_exist_with_valid_frontmatter() -> None:
    cmd_dir = REPO_ROOT / "commands"
    for name in EXPECTED_COMMANDS:
        path = cmd_dir / f"{name}.md"
        assert path.exists(), f"Missing command: {name}"
        content = path.read_text()
        m = FRONTMATTER.match(content)
        assert m is not None, f"{name}: missing YAML frontmatter"
        front = m.group(1)
        assert "description:" in front, f"{name}: missing description"
