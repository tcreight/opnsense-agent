"""Always-on secrets leakage scan over the working tree.

This test fails CI if anything that looks like an OPNsense API key,
SSH private key, or .env file ends up tracked in git.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Binary-ish file suffixes we shouldn't try to decode as UTF-8 text.
_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico"}

# OPNsense API keys are base64ish, ~60 chars. Match strings that look exactly
# like that, in contexts that suggest they're real (assignment to api_key/secret).
# Quotes around the value are optional so we also catch unquoted YAML/.env-style
# assignments like `api_key: REALKEY1234...`.
API_KEY_ASSIGNMENT = re.compile(
    r"""(api[_-]?(?:key|secret))\s*[:=]\s*["']?([A-Za-z0-9+/=]{40,})["']?""",
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

# Obvious non-secret placeholder values we should never flag.
_PLACEHOLDER_LITERALS = {
    "...",
    "your-key-here",
    "placeholder",
    "changeme",
    "changeme123",
    "<api_key>",
    "<api_secret>",
    "<your_key_here>",
    "$opn_api_key",
    "${opn_api_key}",
    "$opn_api_secret",
    "${opn_api_secret}",
}


def _is_placeholder(value: str) -> bool:
    """Return True if the matched value is an obvious non-secret placeholder."""
    lowered = value.lower()
    if lowered in _PLACEHOLDER_LITERALS:
        return True
    # Anything wrapped in <...> is a placeholder by convention.
    if lowered.startswith("<") and lowered.endswith(">"):
        return True
    # Single character repeated for the entire length (e.g. 40 A's, 50 0's, xxxx...).
    if len(value) > 0 and len(set(value)) == 1:
        return True
    return False


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
        if path.suffix in _BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        # Skip this test file — it contains the patterns by definition.
        if path.name == "test_no_secrets_in_repo.py":
            continue
        for match in API_KEY_ASSIGNMENT.finditer(text):
            value = match.group(2)
            if _is_placeholder(value):
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")
    assert not offenders, "Possible secret in tracked files:\n" + "\n".join(offenders)


def test_no_ssh_private_keys_in_tracked_files() -> None:
    """No tracked file may contain a PEM/OpenSSH private key header."""
    offenders: list[str] = []
    for path in _git_tracked_files():
        if path.suffix in _BINARY_SUFFIXES:
            continue
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
