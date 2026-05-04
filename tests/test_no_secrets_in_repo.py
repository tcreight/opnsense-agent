"""Always-on secrets leakage scan over the working tree.

This test fails CI if anything that looks like an OPNsense API key,
SSH private key, or .env file ends up tracked in git.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# OPNsense API keys are base64ish, ~60 chars. Match strings that look exactly
# like that, in contexts that suggest they're real (assignment to api_key/secret).
API_KEY_ASSIGNMENT = re.compile(
    r"""(api[_-]?(?:key|secret))\s*[:=]\s*["']([A-Za-z0-9+/=]{40,})["']""",
    re.IGNORECASE,
)
SSH_PRIVATE_KEY_HEADER = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |ENCRYPTED )?PRIVATE KEY-----"
)

REQUIRED_GITIGNORE_PATTERNS = [
    ".env",
    "*.key",
    "*.pem",
    "*_rsa",
    "*_ed25519",
    "secrets/",
    "runs/",
    "*.backup.xml",
    "apikey.txt",
]


def _git_tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [REPO_ROOT / line for line in result.stdout.splitlines() if line]


def test_no_api_key_assignments_in_tracked_files() -> None:
    """No tracked file may contain api_key/api_secret = "<long-base64ish-string>"."""
    offenders: list[str] = []
    for path in _git_tracked_files():
        if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".ico"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        # Skip this test file — it contains the patterns by definition.
        if path.name == "test_no_secrets_in_repo.py":
            continue
        for match in API_KEY_ASSIGNMENT.finditer(text):
            # Allow obvious placeholders.
            value = match.group(2)
            if value.lower() in {"...", "your-key-here", "x" * len(value)}:
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")
    assert not offenders, "Possible secret in tracked files:\n" + "\n".join(offenders)


def test_no_ssh_private_keys_in_tracked_files() -> None:
    offenders: list[str] = []
    for path in _git_tracked_files():
        if path.name == "test_no_secrets_in_repo.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if SSH_PRIVATE_KEY_HEADER.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"SSH private key header found in: {offenders}"


def test_gitignore_covers_required_patterns() -> None:
    gitignore_path = REPO_ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore is missing"
    content = gitignore_path.read_text(encoding="utf-8")
    missing = [p for p in REQUIRED_GITIGNORE_PATTERNS if p not in content]
    assert not missing, f".gitignore missing required patterns: {missing}"
