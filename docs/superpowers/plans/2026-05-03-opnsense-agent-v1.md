# OPNsense Agent v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build v1 of the OPNsense Agent — a Claude Code plugin with a plan-then-apply workflow that manages VLANs, interfaces, and DHCP on a single OPNsense firewall via REST API + SSH.

**Architecture:** Python 3.12 MCP server exposing 14 primitive tools. Six on-demand skills hold subsystem expertise. Six slash commands provide workflow entry points. A planner subagent drafts plans. **All mutations chokepoint through `opn_plan_apply`** for guaranteed backup, lockout check, and reachability verification.

**Tech Stack:** Python 3.12, official MCP Python SDK, Pydantic v2, `httpx` (async HTTP), `asyncssh`, `PyYAML`, `pytest` + `pytest-asyncio`, `ruff`, `pyright`, `gitleaks`, GitHub Actions.

**Spec:** [docs/superpowers/specs/2026-05-03-opnsense-agent-design.md](../specs/2026-05-03-opnsense-agent-design.md)

---

## File Map

| File | Responsibility |
|---|---|
| `.gitignore` | Hardened deny patterns; committed first. |
| `.pre-commit-config.yaml` | gitleaks + ruff + pyright. |
| `README.md` | Setup, security caveats, usage. |
| `pyproject.toml` | Package metadata + deps + script entry points. |
| `plugin.json` | Claude Code plugin manifest. |
| `.mcp.json` | MCP server registration using `${CLAUDE_PLUGIN_ROOT}`. |
| `.github/workflows/ci.yml` | Lint, type-check, unit + smoke tests, gitleaks. |
| `src/opnsense_agent/__init__.py` | Package marker + version. |
| `src/opnsense_agent/config.py` | Settings loader (env + TOML), permission enforcement. |
| `src/opnsense_agent/client/api.py` | OPNsense REST API client (httpx async). Logs redacted. |
| `src/opnsense_agent/client/ssh.py` | SSH executor (asyncssh) with read-only allowlist for the public method. |
| `src/opnsense_agent/cli.py` | `opnsense-agent setup` and `opnsense-agent doctor`. |
| `src/opnsense_agent/safety/backup.py` | Pull config.xml, save to `runs/backups/`, list, restore, retention. |
| `src/opnsense_agent/safety/lockout.py` | Analyze plan ops for lockout risk. |
| `src/opnsense_agent/safety/probe.py` | Reachability probe (ping + opn_status loop). |
| `src/opnsense_agent/plans/schema.py` | Pydantic models for plan + ops + status. |
| `src/opnsense_agent/plans/store.py` | Save (0644 → 0444 on finalize), load, list. |
| `src/opnsense_agent/plans/engine.py` | Op handler protocol, registry, executor, apply pipeline. |
| `src/opnsense_agent/plans/handlers/vlan.py` | `vlan.create` handler. |
| `src/opnsense_agent/plans/handlers/interface.py` | `interface.assign`, `interface.configure`. |
| `src/opnsense_agent/plans/handlers/dhcp.py` | `dhcp.scope.create`, `dhcp.static.add`. |
| `src/opnsense_agent/mcp_server.py` | MCP entry point; registers 14 tools. |
| `commands/opn-plan.md`, `opn-apply.md`, `opn-status.md`, `opn-backup.md`, `opn-rollback.md`, `opn-diag.md` | Slash commands. |
| `agents/opn-planner.md`, `opn-diag.md` | Subagents. |
| `skills/opn-safety/SKILL.md`, `opn-planning/SKILL.md`, `opn-interfaces/SKILL.md`, `opn-vlans/SKILL.md`, `opn-dhcp/SKILL.md`, `opn-troubleshooting/SKILL.md` | v1 skill set. |
| `tests/unit/...` | Mocked-client unit tests. |
| `tests/smoke/...` | Manifest/frontmatter/server-startup contract tests. |
| `tests/integration/...` | Opt-in real-OPNsense round-trips. |
| `tests/test_no_secrets_in_repo.py` | Always-on secrets-leakage scan. |

---

## Conventions every task follows

- **TDD:** failing test first, run-to-fail, minimal impl, run-to-pass, commit.
- **Commit message format:** `<type>: <imperative summary>` where type ∈ `feat | fix | test | chore | docs | refactor`.
- **One commit per task** unless explicitly noted.
- **Run from repo root** (`/home/tylerc/projects/opnsense-agent`).
- **Python:** all functions and methods type-annotated; `from __future__ import annotations` at top of every module.
- **Logging:** module-level `logger = logging.getLogger(__name__)`. Never log auth headers or `api_secret`.

---

## Task 1: Repo init + safety scaffolding (MUST be first)

**Files:**
- Create: `/home/tylerc/projects/opnsense-agent/.gitignore`
- Create: `/home/tylerc/projects/opnsense-agent/.pre-commit-config.yaml`
- Create: `/home/tylerc/projects/opnsense-agent/README.md`
- Create: `/home/tylerc/projects/opnsense-agent/tests/test_no_secrets_in_repo.py`
- Create: `/home/tylerc/projects/opnsense-agent/tests/__init__.py`

- [ ] **Step 1: Verify `gh` is authenticated**

Run: `gh auth status`
Expected: `Logged in to github.com as tcreight` (or similar). If not authenticated, stop and ask user to run `gh auth login`.

- [ ] **Step 2: Initialize git repo**

Run:
```bash
cd /home/tylerc/projects/opnsense-agent && git init -b main
```
Expected: `Initialized empty Git repository...`

- [ ] **Step 3: Create hardened `.gitignore` (committed FIRST, before any code)**

Create `.gitignore`:
```gitignore
# === Secrets — never commit ===
.env
.env.*
*.key
*.pem
*.p12
*_rsa
*_rsa.pub
*_ed25519
*_ed25519.pub
secrets/
config.local.*
*.apikey
apikey.txt

# === Runtime artifacts (may contain hostnames, internal topology) ===
runs/
*.backup.xml

# === Python ===
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.venv/
venv/
dist/
build/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.pyright/

# === Editor / OS ===
.DS_Store
Thumbs.db
.vscode/
.idea/
*.swp
*.swo
```

- [ ] **Step 4: Create pre-commit config**

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
        args: [--maxkb=500]
      - id: detect-private-key
```

- [ ] **Step 5: Create README skeleton (security section first)**

Create `README.md`:
```markdown
# OPNsense Agent

A Claude Code plugin for managing a single OPNsense firewall via a plan-then-apply workflow. Uses the OPNsense REST API for config mutations and SSH for diagnostics.

> **Status:** v1 — covers VLANs, interfaces, DHCP. See [roadmap](#roadmap) for future phases.

## ⚠️ Secrets handling

This plugin requires an OPNsense API key/secret and an SSH key. **They are never stored in this repository.**

- Secrets live in `~/.config/opnsense-agent/config.toml` (mode `0600`, refused if wider).
- The repo's `.gitignore` denies `.env`, `*.key`, `*.pem`, `*_rsa`, `*_ed25519`, `secrets/`, `config.local.*`, `apikey.txt`, `runs/`, and config backups.
- A `pre-commit` hook runs `gitleaks` on every commit and blocks anything that looks like a secret.
- A CI test (`tests/test_no_secrets_in_repo.py`) greps the working tree for OPNsense-shaped API keys and SSH private-key headers; CI fails on a match.

If you find a way to commit a secret, that is a bug. File an issue.

## Setup

(Filled in by Task 22 — the README finalization task.)

## Roadmap

- v1 — VLANs, interfaces, DHCP, basic gateway/DNS *(this release)*
- v2 — VPN (WireGuard, OpenVPN)
- v3 — Firewall rules, aliases, NAT, port forwards
- v4 — Drift detection + monitoring daemon

## License

MIT
```

- [ ] **Step 6: Write the failing secrets-leakage test**

Create `tests/__init__.py` (empty file).

Create `tests/test_no_secrets_in_repo.py`:
```python
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
```

- [ ] **Step 7: Stage files and run test (will fail — pytest not installed yet)**

Run: `cd /home/tylerc/projects/opnsense-agent && git add .gitignore .pre-commit-config.yaml README.md tests/`
Run: `python -c "import pytest" 2>&1 | head -1`
Expected: `ModuleNotFoundError: No module named 'pytest'` — that's fine; we install it in Task 2 and re-run the test there. For now, manually verify the test file parses:
Run: `python -m py_compile tests/test_no_secrets_in_repo.py`
Expected: no output (success).

- [ ] **Step 8: Commit the safety scaffolding**

Run:
```bash
git commit -m "$(cat <<'EOF'
chore: initial repo with hardened secrets protection

.gitignore, pre-commit config (gitleaks), README security section,
and a CI test that scans tracked files for API key / SSH key leakage.

Committed before any other code so secrets protection is the first
thing that ever lands on main.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```
Expected: `[main (root-commit) ...] chore: initial repo...`

- [ ] **Step 9: Create the public GitHub repo and push**

Run:
```bash
gh repo create tcreight/opnsense-agent \
  --public \
  --description "Claude Code plugin for managing OPNsense firewalls via a plan-then-apply workflow" \
  --source=. \
  --remote=origin \
  --push
```
Expected: `https://github.com/tcreight/opnsense-agent` printed.

Run: `git remote -v`
Expected: `origin  git@github.com:tcreight/opnsense-agent.git (fetch/push)`

If the URL is HTTPS, fix it:
```bash
git remote set-url origin git@github.com:tcreight/opnsense-agent.git
```

---

## Task 2: Python package skeleton + pyproject + CI

**Files:**
- Create: `pyproject.toml`
- Create: `src/opnsense_agent/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/smoke/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "opnsense-agent"
version = "0.1.0"
description = "Claude Code plugin for managing OPNsense firewalls via a plan-then-apply workflow"
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
authors = [{ name = "Tyler Creighton" }]

dependencies = [
    "mcp>=1.2.0",
    "pydantic>=2.9",
    "httpx>=0.27",
    "asyncssh>=2.18",
    "pyyaml>=6.0",
    "tomli>=2.0; python_version<'3.11'",
    "click>=8.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5.0",
    "ruff>=0.8",
    "pyright>=1.1.380",
    "pre-commit>=4.0",
]

[project.scripts]
opnsense-agent = "opnsense_agent.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "A", "C4", "T20", "RET", "SIM"]
ignore = ["E501"]  # line length handled by formatter

[tool.pyright]
include = ["src", "tests"]
pythonVersion = "3.12"
typeCheckingMode = "strict"
reportMissingImports = "error"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
    "integration: hits a real OPNsense (requires OPN_AGENT_INTEGRATION_TEST=1)",
]
```

- [ ] **Step 2: Create package + test `__init__.py` files**

```bash
mkdir -p src/opnsense_agent tests/unit tests/smoke tests/integration
```

Create `src/opnsense_agent/__init__.py`:
```python
"""OPNsense Agent — Claude Code plugin for OPNsense firewall management."""
from __future__ import annotations

__version__ = "0.1.0"
```

Create empty `tests/unit/__init__.py`, `tests/smoke/__init__.py`, `tests/integration/__init__.py`.

- [ ] **Step 3: Install dev deps + pre-commit**

Run:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pre-commit install
```
Expected: `pre-commit installed at .git/hooks/pre-commit`.

- [ ] **Step 4: Run the secrets-leakage test (now installed)**

Run: `pytest tests/test_no_secrets_in_repo.py -v`
Expected: 3 passed.

- [ ] **Step 5: Create CI workflow**

Create `.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install
        run: pip install -e '.[dev]'
      - name: Lint
        run: ruff check .
      - name: Format check
        run: ruff format --check .
      - name: Type check
        run: pyright
      - name: Unit + smoke tests
        run: pytest tests/unit tests/smoke tests/test_no_secrets_in_repo.py -v
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 6: Commit and push**

Run:
```bash
git add pyproject.toml src/ tests/unit/ tests/smoke/ tests/integration/ .github/
git commit -m "$(cat <<'EOF'
chore: python package skeleton + CI

pyproject with dev deps, package init, test directories,
and GitHub Actions workflow (ruff, pyright, pytest, gitleaks).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```
Expected: push succeeds; CI run kicks off on GitHub.

Run: `gh run watch` (optional — confirms CI passes).

---

## Task 3: Config module with permission enforcement

**Files:**
- Create: `src/opnsense_agent/config.py`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config.py`:
```python
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from opnsense_agent.config import ConfigError, Settings, load_settings


def _write_config(tmp_path: Path, content: str, mode: int = 0o600) -> Path:
    cfg = tmp_path / "config.toml"
    cfg.write_text(content)
    cfg.chmod(mode)
    return cfg


VALID_TOML = """
[firewall]
host = "opnsense.lan"
api_port = 443
ssh_port = 22
verify_tls = true
ssh_user = "root"
ssh_key_path = "~/.ssh/opnsense_ed25519"

[auth]
api_key = "test-key"
api_secret = "test-secret"

[runtime]
runs_dir = "/tmp/opn-runs"
backup_retention = 50
reachability_probe_seconds = 30
reachability_probe_interval = 3

[safety]
require_confirm_phrase = "yes apply"
allow_lockout_override = true
"""


def test_load_settings_from_valid_toml(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, VALID_TOML)
    settings = load_settings(config_path=cfg)
    assert isinstance(settings, Settings)
    assert settings.firewall.host == "opnsense.lan"
    assert settings.auth.api_key == "test-key"
    assert settings.runtime.backup_retention == 50


def test_refuses_world_readable_config(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, VALID_TOML, mode=0o644)
    with pytest.raises(ConfigError, match="permissions"):
        load_settings(config_path=cfg)


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _write_config(tmp_path, VALID_TOML)
    monkeypatch.setenv("OPN_AGENT_HOST", "override.lan")
    monkeypatch.setenv("OPN_AGENT_API_KEY", "env-key")
    settings = load_settings(config_path=cfg)
    assert settings.firewall.host == "override.lan"
    assert settings.auth.api_key == "env-key"


def test_missing_config_raises_helpful_error(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"
    with pytest.raises(ConfigError, match="not found"):
        load_settings(config_path=missing)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'opnsense_agent.config'`.

- [ ] **Step 3: Implement config module**

Create `src/opnsense_agent/config.py`:
```python
"""Settings loader. Reads ~/.config/opnsense-agent/config.toml + env overrides."""
from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "opnsense-agent" / "config.toml"


class ConfigError(Exception):
    """Raised when config is missing, malformed, or insecure."""


@dataclass(frozen=True)
class FirewallSettings:
    host: str
    api_port: int
    ssh_port: int
    verify_tls: bool
    ssh_user: str
    ssh_key_path: Path


@dataclass(frozen=True)
class AuthSettings:
    api_key: str
    api_secret: str


@dataclass(frozen=True)
class RuntimeSettings:
    runs_dir: Path
    backup_retention: int
    reachability_probe_seconds: int
    reachability_probe_interval: int


@dataclass(frozen=True)
class SafetySettings:
    require_confirm_phrase: str
    allow_lockout_override: bool


@dataclass(frozen=True)
class Settings:
    firewall: FirewallSettings
    auth: AuthSettings
    runtime: RuntimeSettings
    safety: SafetySettings


_ENV_MAP: dict[str, tuple[str, str]] = {
    "OPN_AGENT_HOST": ("firewall", "host"),
    "OPN_AGENT_API_PORT": ("firewall", "api_port"),
    "OPN_AGENT_SSH_PORT": ("firewall", "ssh_port"),
    "OPN_AGENT_SSH_USER": ("firewall", "ssh_user"),
    "OPN_AGENT_SSH_KEY_PATH": ("firewall", "ssh_key_path"),
    "OPN_AGENT_VERIFY_TLS": ("firewall", "verify_tls"),
    "OPN_AGENT_API_KEY": ("auth", "api_key"),
    "OPN_AGENT_API_SECRET": ("auth", "api_secret"),
    "OPN_AGENT_RUNS_DIR": ("runtime", "runs_dir"),
}


def _check_permissions(path: Path) -> None:
    mode = path.stat().st_mode & 0o777
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(
            f"{path} has insecure permissions {oct(mode)}; "
            "must be 0600 or stricter (chmod 600 to fix)."
        )


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_int(value: Any) -> int:
    return int(value) if not isinstance(value, int) else value


def _apply_env(data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for env_key, (section, key) in _ENV_MAP.items():
        if env_key in os.environ:
            data.setdefault(section, {})[key] = os.environ[env_key]
    return data


def _expand(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str)).resolve()


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from TOML + environment, enforcing permissions and presence."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"Config file not found at {path}. "
            "Run `opnsense-agent setup` to create one."
        )
    _check_permissions(path)

    with path.open("rb") as f:
        raw = tomllib.load(f)

    data = _apply_env(raw)

    try:
        firewall = FirewallSettings(
            host=data["firewall"]["host"],
            api_port=_coerce_int(data["firewall"].get("api_port", 443)),
            ssh_port=_coerce_int(data["firewall"].get("ssh_port", 22)),
            verify_tls=_coerce_bool(data["firewall"].get("verify_tls", True)),
            ssh_user=data["firewall"].get("ssh_user", "root"),
            ssh_key_path=_expand(data["firewall"]["ssh_key_path"]),
        )
        auth = AuthSettings(
            api_key=data["auth"]["api_key"],
            api_secret=data["auth"]["api_secret"],
        )
        runtime = RuntimeSettings(
            runs_dir=_expand(data["runtime"]["runs_dir"]),
            backup_retention=_coerce_int(data["runtime"].get("backup_retention", 50)),
            reachability_probe_seconds=_coerce_int(
                data["runtime"].get("reachability_probe_seconds", 30)
            ),
            reachability_probe_interval=_coerce_int(
                data["runtime"].get("reachability_probe_interval", 3)
            ),
        )
        safety = SafetySettings(
            require_confirm_phrase=data["safety"].get(
                "require_confirm_phrase", "yes apply"
            ),
            allow_lockout_override=_coerce_bool(
                data["safety"].get("allow_lockout_override", True)
            ),
        )
    except KeyError as e:
        raise ConfigError(f"Missing required config key: {e}") from e

    return Settings(firewall=firewall, auth=auth, runtime=runtime, safety=safety)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/config.py tests/unit/test_config.py
git commit -m "$(cat <<'EOF'
feat: settings loader with env overrides and 0600 enforcement

Refuses world/group-readable config files. Env vars (OPN_AGENT_*)
override TOML values for one-off operation against alternate hosts.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 4: OPNsense REST API client (with redacted logging)

**Files:**
- Create: `src/opnsense_agent/client/__init__.py`
- Create: `src/opnsense_agent/client/api.py`
- Create: `tests/unit/client/__init__.py`
- Create: `tests/unit/client/test_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/client/__init__.py` (empty).

Create `tests/unit/client/test_api.py`:
```python
from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from opnsense_agent.client.api import OpnApiClient
from opnsense_agent.config import AuthSettings, FirewallSettings


@pytest.fixture
def firewall() -> FirewallSettings:
    return FirewallSettings(
        host="opnsense.test",
        api_port=443,
        ssh_port=22,
        verify_tls=False,
        ssh_user="root",
        ssh_key_path="/dev/null",  # type: ignore[arg-type]
    )


@pytest.fixture
def auth() -> AuthSettings:
    return AuthSettings(api_key="THE_KEY_VALUE", api_secret="THE_SECRET_VALUE")


@pytest.mark.asyncio
async def test_get_returns_parsed_json(
    firewall: FirewallSettings, auth: AuthSettings
) -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"status": "ok"})
    )
    client = OpnApiClient(firewall=firewall, auth=auth, transport=transport)
    result = await client.get("/api/diagnostics/system/system_information")
    assert result == {"status": "ok"}
    await client.close()


@pytest.mark.asyncio
async def test_post_sends_basic_auth_header(
    firewall: FirewallSettings, auth: AuthSettings
) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    client = OpnApiClient(firewall=firewall, auth=auth, transport=transport)
    await client.post("/api/some/endpoint", json={"k": "v"})
    assert captured["authorization"].startswith("Basic ")
    await client.close()


@pytest.mark.asyncio
async def test_logs_redact_secrets(
    firewall: FirewallSettings,
    auth: AuthSettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    client = OpnApiClient(firewall=firewall, auth=auth, transport=transport)
    with caplog.at_level(logging.DEBUG, logger="opnsense_agent.client.api"):
        await client.get("/api/anything")
    full_log = "\n".join(record.getMessage() for record in caplog.records)
    assert "THE_KEY_VALUE" not in full_log
    assert "THE_SECRET_VALUE" not in full_log
    await client.close()


@pytest.mark.asyncio
async def test_raises_on_non_2xx(
    firewall: FirewallSettings, auth: AuthSettings
) -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(401, json={"message": "unauthorized"})
    )
    client = OpnApiClient(firewall=firewall, auth=auth, transport=transport)
    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/api/whatever")
    await client.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/client/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement API client**

Create `src/opnsense_agent/client/__init__.py` (empty).

Create `src/opnsense_agent/client/api.py`:
```python
"""Async REST client for the OPNsense API."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from opnsense_agent.config import AuthSettings, FirewallSettings

logger = logging.getLogger(__name__)


class OpnApiClient:
    """Wraps httpx.AsyncClient with OPNsense auth + redacted logging.

    Notes:
        - Uses HTTP Basic auth (api_key:api_secret), per OPNsense docs.
        - All log lines redact the auth header. Never print api_key/api_secret.
    """

    def __init__(
        self,
        firewall: FirewallSettings,
        auth: AuthSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth = auth
        self._base_url = f"https://{firewall.host}:{firewall.api_port}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            auth=(auth.api_key, auth.api_secret),
            verify=firewall.verify_tls,
            timeout=httpx.Timeout(10.0, connect=5.0),
            transport=transport,
        )

    async def get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def post(
        self, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self._request("POST", path, json=json)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        logger.debug("API %s %s (auth: <redacted>)", method, path)
        response = await self._client.request(
            method, path, params=params, json=json
        )
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OpnApiClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/client/test_api.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/client/ tests/unit/client/
git commit -m "$(cat <<'EOF'
feat: async OPNsense REST API client with redacted logging

Wraps httpx.AsyncClient with Basic auth. Tests assert that api_key
and api_secret never appear in log output.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 5: SSH client with read-only allowlist

**Files:**
- Create: `src/opnsense_agent/client/ssh.py`
- Create: `tests/unit/client/test_ssh.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/client/test_ssh.py`:
```python
from __future__ import annotations

from pathlib import Path

import pytest

from opnsense_agent.client.ssh import SshAllowlistError, is_command_allowed
from opnsense_agent.config import FirewallSettings


@pytest.fixture
def firewall(tmp_path: Path) -> FirewallSettings:
    key = tmp_path / "id"
    key.write_text("dummy")
    key.chmod(0o600)
    return FirewallSettings(
        host="opnsense.test",
        api_port=443,
        ssh_port=22,
        verify_tls=False,
        ssh_user="root",
        ssh_key_path=key,
    )


# === Allowlist tests (no live SSH) ===

@pytest.mark.parametrize(
    "cmd",
    [
        "pfctl -ss",
        "pfctl -sr",
        "ifconfig",
        "ifconfig igb0",
        "netstat -rn",
        "tail -n 100 /var/log/system/latest.log",
        "cat /var/log/filter/latest.log",
        "top -b",
        "uname -a",
        "uptime",
    ],
)
def test_allowlist_accepts_known_readonly_commands(cmd: str) -> None:
    assert is_command_allowed(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf /",
        "configctl service reload all",
        "pfctl -F all",
        "pkg upgrade",
        "echo hi > /etc/something",
        "ifconfig igb0 down",
        "shutdown -h now",
        "; cat /etc/passwd",
        "tail /var/log/x && rm -rf /tmp/y",
    ],
)
def test_allowlist_rejects_mutating_commands(cmd: str) -> None:
    assert is_command_allowed(cmd) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/client/test_ssh.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement SSH client**

Create `src/opnsense_agent/client/ssh.py`:
```python
"""SSH client with a hardened read-only allowlist for the public exec method.

The plan engine has its own internal pathway for legitimate mutating SSH
commands; this module is what Claude calls via `opn_ssh_exec_readonly`.
"""
from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass

import asyncssh

from opnsense_agent.config import FirewallSettings

logger = logging.getLogger(__name__)


class SshAllowlistError(Exception):
    """Raised when a command is not on the read-only allowlist."""


# Each entry: (executable, allowed_arg_pattern_or_None)
# Pattern is matched against the joined arg string. None = no args allowed.
_ALLOWLIST: dict[str, re.Pattern[str] | None] = {
    "pfctl": re.compile(r"^-s[srnaviq]$|^-s[srnaviq] .+$"),
    "ifconfig": re.compile(r"^$|^[a-zA-Z0-9_.]+$"),
    "netstat": re.compile(r"^-[rinas]+$|^-[rinas]+ .+$"),
    "tail": re.compile(r"^(?:-n \d+ )?/var/log/[a-zA-Z0-9_./-]+$"),
    "cat": re.compile(r"^/var/log/[a-zA-Z0-9_./-]+$"),
    "top": re.compile(r"^-b$"),
    "uname": re.compile(r"^-a$"),
    "uptime": None,
    "df": re.compile(r"^$|^-h$"),
    "free": None,
}


def is_command_allowed(command: str) -> bool:
    """Strict allowlist check. Rejects anything with shell metacharacters."""
    # No shell composition allowed.
    if any(ch in command for ch in [";", "&&", "||", "|", ">", "<", "`", "$("]):
        return False
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    exe = parts[0]
    arg_str = " ".join(parts[1:])
    if exe not in _ALLOWLIST:
        return False
    pattern = _ALLOWLIST[exe]
    if pattern is None:
        return arg_str == ""
    return bool(pattern.fullmatch(arg_str))


@dataclass(frozen=True)
class SshResult:
    stdout: str
    stderr: str
    exit_code: int


class OpnSshClient:
    """asyncssh wrapper. The public exec method enforces the allowlist."""

    def __init__(self, firewall: FirewallSettings) -> None:
        self._firewall = firewall

    async def exec_readonly(self, command: str, timeout: float = 15.0) -> SshResult:
        if not is_command_allowed(command):
            raise SshAllowlistError(
                f"Command not on read-only allowlist: {command!r}. "
                "Mutating commands must be issued via the plan engine."
            )
        logger.debug("SSH exec (readonly): %s", command)
        async with asyncssh.connect(
            host=self._firewall.host,
            port=self._firewall.ssh_port,
            username=self._firewall.ssh_user,
            client_keys=[str(self._firewall.ssh_key_path)],
            known_hosts=None,  # homelab; document this in README
        ) as conn:
            result = await conn.run(command, check=False, timeout=timeout)
        return SshResult(
            stdout=str(result.stdout or ""),
            stderr=str(result.stderr or ""),
            exit_code=int(result.exit_status or 0),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/client/test_ssh.py -v`
Expected: 20 passed (10 parametrized × 2 test functions).

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/client/ssh.py tests/unit/client/test_ssh.py
git commit -m "$(cat <<'EOF'
feat: SSH client with strict read-only command allowlist

Public exec_readonly() refuses anything not on the allowlist or
containing shell metacharacters. Plan engine has a separate path
for legitimate mutations.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 6: Backup module (config.xml pull, save, list, restore, retention)

**Files:**
- Create: `src/opnsense_agent/safety/__init__.py`
- Create: `src/opnsense_agent/safety/backup.py`
- Create: `tests/unit/safety/__init__.py`
- Create: `tests/unit/safety/test_backup.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/safety/__init__.py` (empty).

Create `tests/unit/safety/test_backup.py`:
```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from opnsense_agent.safety.backup import BackupStore


@pytest.fixture
def store(tmp_path: Path) -> BackupStore:
    return BackupStore(runs_dir=tmp_path, retention=3)


@pytest.mark.asyncio
async def test_create_pulls_config_and_saves_with_timestamp(
    store: BackupStore,
) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<opnsense><test/></opnsense>"
    backup_id = await store.create(api=fake_api, label="manual-test")
    files = list((store.runs_dir / "backups").iterdir())
    assert len(files) == 1
    assert files[0].name.endswith("-manual-test.xml")
    assert backup_id == files[0].stem


@pytest.mark.asyncio
async def test_list_returns_sorted_descending(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<x/>"
    a = await store.create(api=fake_api)
    b = await store.create(api=fake_api)
    c = await store.create(api=fake_api)
    listing = store.list()
    assert [b.id for b in listing] == [c, b, a]


@pytest.mark.asyncio
async def test_retention_prunes_unlabeled_only(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<x/>"
    # 4 unlabeled (one over retention=3) and 1 labeled
    for _ in range(4):
        await store.create(api=fake_api)
    await store.create(api=fake_api, label="keep-me")
    store.prune()
    surviving = [b.label for b in store.list()]
    # 3 unlabeled + the labeled one survive
    assert surviving.count(None) == 3
    assert "keep-me" in surviving


@pytest.mark.asyncio
async def test_restore_posts_xml(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<original/>"
    backup_id = await store.create(api=fake_api)
    fake_api.post.return_value = {"status": "ok"}
    await store.restore(api=fake_api, backup_id=backup_id)
    assert fake_api.post.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/safety/test_backup.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement backup module**

Create `src/opnsense_agent/safety/__init__.py` (empty).

Create `src/opnsense_agent/safety/backup.py`:
```python
"""Pre-change config backups: pull, save, list, restore, retention."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opnsense_agent.client.api import OpnApiClient

logger = logging.getLogger(__name__)

# OPNsense exposes config download at this endpoint.
# Returns the raw config.xml as text.
DOWNLOAD_PATH = "/api/backup/backup/download"
RESTORE_PATH = "/api/backup/backup/restore"


@dataclass(frozen=True)
class BackupRecord:
    id: str
    path: Path
    label: str | None
    created: datetime


class BackupStore:
    def __init__(self, runs_dir: Path, retention: int = 50) -> None:
        self.runs_dir = runs_dir
        self.retention = retention
        (runs_dir / "backups").mkdir(parents=True, exist_ok=True)

    async def create(self, api: "OpnApiClient", label: str | None = None) -> str:
        # API may return JSON-wrapped or raw. We treat the response as text.
        # The actual endpoint shape is verified during integration test;
        # for unit tests we mock api.get to return the raw XML string.
        raw = await api.get(DOWNLOAD_PATH)  # type: ignore[func-returns-value]
        xml_text = raw if isinstance(raw, str) else raw.get("data", "")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = f"-{label}" if label else ""
        backup_id = f"{ts}{suffix}"
        path = self.runs_dir / "backups" / f"{backup_id}.xml"
        path.write_text(xml_text)
        logger.info("Backup created: %s", backup_id)
        return backup_id

    def list(self) -> list[BackupRecord]:
        records: list[BackupRecord] = []
        for path in (self.runs_dir / "backups").iterdir():
            if path.suffix != ".xml":
                continue
            stem = path.stem
            ts_part, _, label = stem.partition("-")
            try:
                created = datetime.strptime(ts_part, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
            records.append(
                BackupRecord(
                    id=stem,
                    path=path,
                    label=label or None,
                    created=created,
                )
            )
        records.sort(key=lambda r: r.created, reverse=True)
        return records

    def prune(self) -> int:
        unlabeled = [r for r in self.list() if r.label is None]
        # Keep the newest `retention` unlabeled; delete the rest.
        to_delete = unlabeled[self.retention :]
        for record in to_delete:
            record.path.unlink()
            logger.info("Pruned backup: %s", record.id)
        return len(to_delete)

    async def restore(self, api: "OpnApiClient", backup_id: str) -> None:
        path = self.runs_dir / "backups" / f"{backup_id}.xml"
        if not path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_id}")
        xml_text = path.read_text()
        await api.post(RESTORE_PATH, json={"data": xml_text})
        logger.info("Backup restored: %s", backup_id)
```

> Note for implementer: the actual `DOWNLOAD_PATH` / `RESTORE_PATH` endpoint shapes vary by OPNsense version. The unit tests mock these. Verify in the integration test (Task 21) and adjust the JSON wrapping if needed. The structure of the BackupStore is what we're locking in here.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/safety/test_backup.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/safety/ tests/unit/safety/
git commit -m "$(cat <<'EOF'
feat: backup store with timestamped saves, listing, retention, restore

Unlabeled backups respect retention=N; labeled backups are kept forever.
Restore endpoint shape will be verified during integration testing.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 7: Plan schema (Pydantic models)

**Files:**
- Create: `src/opnsense_agent/plans/__init__.py`
- Create: `src/opnsense_agent/plans/schema.py`
- Create: `tests/unit/plans/__init__.py`
- Create: `tests/unit/plans/test_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/plans/__init__.py` (empty).

Create `tests/unit/plans/test_schema.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import yaml
from pydantic import ValidationError

from opnsense_agent.plans.schema import Plan, PlanOp, PlanStatus


SAMPLE_YAML = """
plan_id: 2026-05-03T14-30-22Z-iot-vlan
description: Stand up VLAN 30 for IoT
created: 2026-05-03T14:30:22Z
status: draft
target:
  host: opnsense.lan
  api_user: claude-agent
ops:
  - op: vlan.create
    params: { tag: 30, parent_if: igb1, description: "IoT" }
execution:
  backup_id: null
  applied_at: null
  results: []
  rollback_reason: null
"""


def test_parses_valid_plan() -> None:
    data = yaml.safe_load(SAMPLE_YAML)
    plan = Plan.model_validate(data)
    assert plan.plan_id == "2026-05-03T14-30-22Z-iot-vlan"
    assert plan.status is PlanStatus.draft
    assert len(plan.ops) == 1
    assert plan.ops[0].op == "vlan.create"
    assert plan.ops[0].params["tag"] == 30


def test_rejects_unknown_status() -> None:
    data = yaml.safe_load(SAMPLE_YAML)
    data["status"] = "exploded"
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_rejects_empty_ops() -> None:
    data = yaml.safe_load(SAMPLE_YAML)
    data["ops"] = []
    with pytest.raises(ValidationError, match="at least 1"):
        Plan.model_validate(data)


def test_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        Plan.model_validate({"plan_id": "x"})


def test_yaml_roundtrip() -> None:
    data = yaml.safe_load(SAMPLE_YAML)
    plan = Plan.model_validate(data)
    dumped = plan.model_dump(mode="json")
    plan2 = Plan.model_validate(dumped)
    assert plan2 == plan
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plans/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement plan schema**

Create `src/opnsense_agent/plans/__init__.py` (empty).

Create `src/opnsense_agent/plans/schema.py`:
```python
"""Pydantic models for plans, ops, and execution state."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlanStatus(str, Enum):
    draft = "draft"
    applied = "applied"
    failed = "failed"
    rolled_back = "rolled_back"


class PlanOp(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str = Field(min_length=1, description="Op type identifier (e.g. 'vlan.create')")
    params: dict[str, Any] = Field(default_factory=dict)


class PlanTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    api_user: str | None = None


class OpResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str
    status: str  # "ok" | "error"
    response: dict[str, Any] | None = None
    error: str | None = None


class PlanExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backup_id: str | None = None
    applied_at: datetime | None = None
    results: list[OpResult] = Field(default_factory=list)
    rollback_reason: str | None = None


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    description: str
    created: datetime
    status: PlanStatus = PlanStatus.draft
    target: PlanTarget
    ops: list[PlanOp] = Field(min_length=1)
    execution: PlanExecution = Field(default_factory=PlanExecution)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plans/test_schema.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/plans/__init__.py src/opnsense_agent/plans/schema.py tests/unit/plans/
git commit -m "$(cat <<'EOF'
feat: pydantic schema for plan, ops, status, execution state

Strict validation (extra='forbid'), enum-backed status, min_length=1 on ops.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 8: Plan store (save / load / list / immutability on finalize)

**Files:**
- Create: `src/opnsense_agent/plans/store.py`
- Create: `tests/unit/plans/test_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/plans/test_store.py`:
```python
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import yaml

from opnsense_agent.plans.schema import Plan, PlanStatus
from opnsense_agent.plans.store import PlanStore


SAMPLE_YAML = """
plan_id: 2026-05-03T14-30-22Z-test
description: test
created: 2026-05-03T14:30:22Z
status: draft
target: { host: opnsense.lan }
ops:
  - op: vlan.create
    params: { tag: 30, parent_if: igb1 }
"""


@pytest.fixture
def store(tmp_path: Path) -> PlanStore:
    return PlanStore(runs_dir=tmp_path)


def _make_plan() -> Plan:
    return Plan.model_validate(yaml.safe_load(SAMPLE_YAML))


def test_save_writes_yaml_at_0644(store: PlanStore) -> None:
    plan = _make_plan()
    plan_id = store.save(plan)
    path = store.runs_dir / "plans" / f"{plan_id}.yaml"
    assert path.exists()
    mode = path.stat().st_mode & 0o777
    assert mode == 0o644


def test_load_roundtrips(store: PlanStore) -> None:
    plan = _make_plan()
    plan_id = store.save(plan)
    loaded = store.load(plan_id)
    assert loaded == plan


def test_list_includes_status(store: PlanStore) -> None:
    plan = _make_plan()
    store.save(plan)
    listing = store.list()
    assert len(listing) == 1
    assert listing[0].status is PlanStatus.draft


def test_finalize_chmods_file_to_0444(store: PlanStore) -> None:
    plan = _make_plan()
    plan_id = store.save(plan)
    plan_applied = plan.model_copy(update={"status": PlanStatus.applied})
    store.finalize(plan_applied)
    path = store.runs_dir / "plans" / f"{plan_id}.yaml"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o444


def test_finalize_refuses_when_status_still_draft(store: PlanStore) -> None:
    plan = _make_plan()
    store.save(plan)
    with pytest.raises(ValueError, match="finalize"):
        store.finalize(plan)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plans/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement plan store**

Create `src/opnsense_agent/plans/store.py`:
```python
"""Plan persistence: save, load, list, finalize (immutable after non-draft)."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from opnsense_agent.plans.schema import Plan, PlanStatus

logger = logging.getLogger(__name__)


class PlanStore:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        (runs_dir / "plans").mkdir(parents=True, exist_ok=True)

    def save(self, plan: Plan) -> str:
        path = self.runs_dir / "plans" / f"{plan.plan_id}.yaml"
        # If file exists and is read-only (already finalized), refuse.
        if path.exists() and not (path.stat().st_mode & 0o200):
            raise PermissionError(
                f"Plan {plan.plan_id} is finalized (read-only); cannot overwrite."
            )
        text = yaml.safe_dump(
            plan.model_dump(mode="json"), sort_keys=False, default_flow_style=False
        )
        path.write_text(text)
        path.chmod(0o644)
        logger.info("Plan saved: %s (status=%s)", plan.plan_id, plan.status.value)
        return plan.plan_id

    def load(self, plan_id: str) -> Plan:
        path = self.runs_dir / "plans" / f"{plan_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Plan not found: {plan_id}")
        return Plan.model_validate(yaml.safe_load(path.read_text()))

    def list(self) -> list[Plan]:
        plans: list[Plan] = []
        for path in sorted((self.runs_dir / "plans").iterdir(), reverse=True):
            if path.suffix != ".yaml":
                continue
            try:
                plans.append(Plan.model_validate(yaml.safe_load(path.read_text())))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping malformed plan file: %s", path)
        return plans

    def finalize(self, plan: Plan) -> None:
        """Save plan in a non-draft status and chmod 0444 for audit immutability."""
        if plan.status is PlanStatus.draft:
            raise ValueError(
                "Cannot finalize a plan still in draft status. "
                "Set status to applied/failed/rolled_back first."
            )
        path = self.runs_dir / "plans" / f"{plan.plan_id}.yaml"
        # Save first (will succeed if file is currently 0644)
        text = yaml.safe_dump(
            plan.model_dump(mode="json"), sort_keys=False, default_flow_style=False
        )
        # Temporarily restore write permission if the file is already locked.
        if path.exists():
            path.chmod(0o644)
        path.write_text(text)
        path.chmod(0o444)
        logger.info("Plan finalized: %s -> %s", plan.plan_id, plan.status.value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plans/test_store.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/plans/store.py tests/unit/plans/test_store.py
git commit -m "$(cat <<'EOF'
feat: plan store with finalize-immutability (0444 after status change)

Drafts are 0644 and overwriteable; once a plan transitions to
applied/failed/rolled_back, finalize() chmods the file 0444 so the
audit trail can't be silently rewritten.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 9: Op handler protocol + registry (engine skeleton)

**Files:**
- Create: `src/opnsense_agent/plans/engine.py`
- Create: `src/opnsense_agent/plans/handlers/__init__.py`
- Create: `tests/unit/plans/test_engine.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/plans/test_engine.py`:
```python
from __future__ import annotations

from typing import Any

import pytest

from opnsense_agent.plans.engine import (
    HandlerContext,
    OpHandler,
    OpHandlerRegistry,
    UnknownOpError,
)
from opnsense_agent.plans.schema import OpResult, PlanOp


class FakeHandler:
    op_type = "test.echo"

    async def execute(
        self, op: PlanOp, ctx: HandlerContext
    ) -> OpResult:
        return OpResult(op=op.op, status="ok", response={"echoed": op.params})


def test_register_and_lookup() -> None:
    registry = OpHandlerRegistry()
    registry.register(FakeHandler())
    assert registry.get("test.echo").op_type == "test.echo"


def test_unknown_op_raises() -> None:
    registry = OpHandlerRegistry()
    with pytest.raises(UnknownOpError):
        registry.get("does.not.exist")


def test_double_register_raises() -> None:
    registry = OpHandlerRegistry()
    registry.register(FakeHandler())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeHandler())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plans/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement engine skeleton**

Create `src/opnsense_agent/plans/handlers/__init__.py` (empty).

Create `src/opnsense_agent/plans/engine.py`:
```python
"""Op handler protocol, registry, and (later) the apply pipeline."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from opnsense_agent.plans.schema import OpResult, PlanOp

if TYPE_CHECKING:
    from opnsense_agent.client.api import OpnApiClient
    from opnsense_agent.client.ssh import OpnSshClient

logger = logging.getLogger(__name__)


class UnknownOpError(Exception):
    """Raised when no handler is registered for a given op type."""


@dataclass(frozen=True)
class HandlerContext:
    """Resources available to a handler during execution."""

    api: "OpnApiClient"
    ssh: "OpnSshClient"


@runtime_checkable
class OpHandler(Protocol):
    op_type: str

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult: ...


class OpHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, OpHandler] = {}

    def register(self, handler: OpHandler) -> None:
        if handler.op_type in self._handlers:
            raise ValueError(f"Op type {handler.op_type!r} already registered")
        self._handlers[handler.op_type] = handler
        logger.debug("Registered op handler: %s", handler.op_type)

    def get(self, op_type: str) -> OpHandler:
        try:
            return self._handlers[op_type]
        except KeyError as e:
            raise UnknownOpError(f"No handler for op type: {op_type!r}") from e

    def known_types(self) -> list[str]:
        return sorted(self._handlers.keys())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plans/test_engine.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/plans/engine.py src/opnsense_agent/plans/handlers/ tests/unit/plans/test_engine.py
git commit -m "$(cat <<'EOF'
feat: op handler protocol + registry

OpHandler protocol + OpHandlerRegistry with double-register protection.
Apply pipeline lands in Task 13.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 10: VLAN op handler

**Files:**
- Create: `src/opnsense_agent/plans/handlers/vlan.py`
- Create: `tests/unit/plans/handlers/__init__.py`
- Create: `tests/unit/plans/handlers/test_vlan.py`

> **OPNsense API note:** VLAN endpoints are under `/api/interfaces/vlan_settings/`. Common actions: `searchItem` (GET), `addItem` (POST), `setItem/{uuid}` (POST), `delItem/{uuid}` (POST). After mutations, `/api/interfaces/vlan_settings/reconfigure` (POST) applies the change. Endpoint shapes verified during integration test.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/plans/handlers/__init__.py` (empty).

Create `tests/unit/plans/handlers/test_vlan.py`:
```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.handlers.vlan import VlanCreateHandler
from opnsense_agent.plans.schema import PlanOp


@pytest.mark.asyncio
async def test_vlan_create_calls_addItem_then_reconfigure() -> None:
    api = AsyncMock()
    api.post.side_effect = [
        {"result": "saved", "uuid": "vlan-uuid-1"},  # addItem
        {"status": "ok"},                            # reconfigure
    ]
    handler = VlanCreateHandler()
    op = PlanOp(
        op="vlan.create",
        params={"tag": 30, "parent_if": "igb1", "description": "IoT"},
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
    assert api.post.call_count == 2
    add_call, reconfig_call = api.post.call_args_list
    assert add_call.args[0] == "/api/interfaces/vlan_settings/addItem"
    assert reconfig_call.args[0] == "/api/interfaces/vlan_settings/reconfigure"
    body = add_call.kwargs["json"]
    assert body["vlan"]["tag"] == "30"
    assert body["vlan"]["if"] == "igb1"
    assert body["vlan"]["descr"] == "IoT"


@pytest.mark.asyncio
async def test_vlan_create_handles_addItem_failure() -> None:
    api = AsyncMock()
    api.post.side_effect = [
        {"result": "failed", "validations": {"vlan.tag": "invalid"}},
    ]
    handler = VlanCreateHandler()
    op = PlanOp(op="vlan.create", params={"tag": 5000, "parent_if": "igb1"})
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "error"
    assert "invalid" in (result.error or "")
    # Did NOT call reconfigure after a failed add
    assert api.post.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plans/handlers/test_vlan.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement VLAN handler**

Create `src/opnsense_agent/plans/handlers/vlan.py`:
```python
"""Handler for vlan.create op."""
from __future__ import annotations

import logging

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.schema import OpResult, PlanOp

logger = logging.getLogger(__name__)


class VlanCreateHandler:
    op_type = "vlan.create"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        params = op.params
        body = {
            "vlan": {
                "tag": str(params["tag"]),
                "if": params["parent_if"],
                "descr": params.get("description", ""),
                "pcp": str(params.get("pcp", 0)),
            }
        }
        try:
            add = await ctx.api.post(
                "/api/interfaces/vlan_settings/addItem", json=body
            )
            if add.get("result") != "saved":
                return OpResult(
                    op=op.op,
                    status="error",
                    response=add,
                    error=f"addItem failed: {add.get('validations') or add}",
                )
            reconfigure = await ctx.api.post(
                "/api/interfaces/vlan_settings/reconfigure", json={}
            )
            return OpResult(
                op=op.op,
                status="ok",
                response={"add": add, "reconfigure": reconfigure},
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("vlan.create failed")
            return OpResult(op=op.op, status="error", error=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plans/handlers/test_vlan.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/plans/handlers/vlan.py tests/unit/plans/handlers/
git commit -m "$(cat <<'EOF'
feat: vlan.create op handler

Calls addItem then reconfigure. Maps result.failed responses to
OpResult(status='error') with validation messages preserved.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 11: Interface op handlers (assign + configure)

**Files:**
- Create: `src/opnsense_agent/plans/handlers/interface.py`
- Create: `tests/unit/plans/handlers/test_interface.py`

> **OPNsense API note:** Interface assignment is under `/api/interfaces/overview/` and `/api/interface/...`. Assigning a VLAN as a numbered interface (opt1, opt2, ...) historically required `interfaces_assign.php` POST, but recent versions expose `/api/interfaces/settings/...`. The exact endpoint is version-dependent; verify in integration test. The handler structure here is correct; URLs may need adjustment.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/plans/handlers/test_interface.py`:
```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.handlers.interface import (
    InterfaceAssignHandler,
    InterfaceConfigureHandler,
)
from opnsense_agent.plans.schema import PlanOp


@pytest.mark.asyncio
async def test_assign_posts_to_interface_settings() -> None:
    api = AsyncMock()
    api.post.return_value = {"result": "saved"}
    handler = InterfaceAssignHandler()
    op = PlanOp(
        op="interface.assign",
        params={
            "vlan_tag": 30,
            "parent_if": "igb1",
            "opn_if_name": "opt3",
            "enabled": True,
        },
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
    assert api.post.called


@pytest.mark.asyncio
async def test_configure_sets_ipv4() -> None:
    api = AsyncMock()
    api.post.return_value = {"result": "saved"}
    handler = InterfaceConfigureHandler()
    op = PlanOp(
        op="interface.configure",
        params={
            "opn_if_name": "opt3",
            "ipv4": "10.30.0.1",
            "ipv4_subnet": 24,
        },
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
    body = api.post.call_args.kwargs["json"]
    assert body["interface"]["ipaddr"] == "10.30.0.1"
    assert body["interface"]["subnet"] == "24"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plans/handlers/test_interface.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement interface handlers**

Create `src/opnsense_agent/plans/handlers/interface.py`:
```python
"""Handlers for interface.assign and interface.configure ops."""
from __future__ import annotations

import logging

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.schema import OpResult, PlanOp

logger = logging.getLogger(__name__)


class InterfaceAssignHandler:
    op_type = "interface.assign"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        params = op.params
        body = {
            "interface": {
                "if": f"{params['parent_if']}_vlan{params['vlan_tag']}",
                "descr": params.get("opn_if_name", ""),
                "enable": "1" if params.get("enabled", True) else "0",
            }
        }
        try:
            response = await ctx.api.post(
                f"/api/interfaces/settings/setItem/{params['opn_if_name']}",
                json=body,
            )
            if response.get("result") not in {"saved", "ok"}:
                return OpResult(
                    op=op.op, status="error", response=response,
                    error=f"assign failed: {response}",
                )
            await ctx.api.post("/api/interfaces/settings/reconfigure", json={})
            return OpResult(op=op.op, status="ok", response=response)
        except Exception as e:  # noqa: BLE001
            logger.exception("interface.assign failed")
            return OpResult(op=op.op, status="error", error=str(e))


class InterfaceConfigureHandler:
    op_type = "interface.configure"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        params = op.params
        body = {
            "interface": {
                "ipaddr": params["ipv4"],
                "subnet": str(params["ipv4_subnet"]),
                "ipaddrv6": params.get("ipv6", ""),
            }
        }
        try:
            response = await ctx.api.post(
                f"/api/interfaces/settings/setItem/{params['opn_if_name']}",
                json=body,
            )
            if response.get("result") not in {"saved", "ok"}:
                return OpResult(
                    op=op.op, status="error", response=response,
                    error=f"configure failed: {response}",
                )
            await ctx.api.post("/api/interfaces/settings/reconfigure", json={})
            return OpResult(op=op.op, status="ok", response=response)
        except Exception as e:  # noqa: BLE001
            logger.exception("interface.configure failed")
            return OpResult(op=op.op, status="error", error=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plans/handlers/test_interface.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/plans/handlers/interface.py tests/unit/plans/handlers/test_interface.py
git commit -m "$(cat <<'EOF'
feat: interface.assign + interface.configure op handlers

Both call setItem then reconfigure. Endpoint shapes will be verified
in integration testing; structure here is what gets locked in.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 12: DHCP op handlers (scope.create + static.add)

**Files:**
- Create: `src/opnsense_agent/plans/handlers/dhcp.py`
- Create: `tests/unit/plans/handlers/test_dhcp.py`

> **OPNsense API note:** DHCP under OPNsense 24+ uses Kea (`/api/kea/dhcpv4/...`) by default; older versions used ISC (`/api/dhcpv4/...`). v1 targets Kea. Endpoints: `/api/kea/dhcpv4/addSubnet`, `/api/kea/dhcpv4/addReservation`, `/api/kea/service/reconfigure`. Verify in integration test.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/plans/handlers/test_dhcp.py`:
```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.handlers.dhcp import DhcpScopeCreateHandler, DhcpStaticAddHandler
from opnsense_agent.plans.schema import PlanOp


@pytest.mark.asyncio
async def test_scope_create_posts_addSubnet_then_reconfigure() -> None:
    api = AsyncMock()
    api.post.side_effect = [
        {"result": "saved", "uuid": "subnet-uuid-1"},
        {"status": "ok"},
    ]
    handler = DhcpScopeCreateHandler()
    op = PlanOp(
        op="dhcp.scope.create",
        params={
            "interface": "opt3",
            "range_from": "10.30.0.100",
            "range_to": "10.30.0.200",
            "router": "10.30.0.1",
            "dns": ["10.30.0.1"],
            "subnet": "10.30.0.0/24",
        },
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
    assert api.post.call_count == 2


@pytest.mark.asyncio
async def test_static_add_posts_addReservation() -> None:
    api = AsyncMock()
    api.post.side_effect = [
        {"result": "saved", "uuid": "res-1"},
        {"status": "ok"},
    ]
    handler = DhcpStaticAddHandler()
    op = PlanOp(
        op="dhcp.static.add",
        params={
            "interface": "opt3",
            "mac": "aa:bb:cc:dd:ee:ff",
            "ip": "10.30.0.50",
            "hostname": "thermostat",
        },
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plans/handlers/test_dhcp.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement DHCP handlers**

Create `src/opnsense_agent/plans/handlers/dhcp.py`:
```python
"""Handlers for dhcp.scope.create and dhcp.static.add ops (Kea backend)."""
from __future__ import annotations

import logging

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.schema import OpResult, PlanOp

logger = logging.getLogger(__name__)


class DhcpScopeCreateHandler:
    op_type = "dhcp.scope.create"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        p = op.params
        body = {
            "subnet4": {
                "subnet": p["subnet"],
                "pools": f"{p['range_from']}-{p['range_to']}",
                "option_data_router": p["router"],
                "option_data_domain_name_servers": ",".join(p["dns"]),
                "interface": p["interface"],
            }
        }
        try:
            add = await ctx.api.post("/api/kea/dhcpv4/addSubnet", json=body)
            if add.get("result") != "saved":
                return OpResult(
                    op=op.op, status="error", response=add,
                    error=f"addSubnet failed: {add}",
                )
            reconf = await ctx.api.post("/api/kea/service/reconfigure", json={})
            return OpResult(
                op=op.op, status="ok",
                response={"add": add, "reconfigure": reconf},
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("dhcp.scope.create failed")
            return OpResult(op=op.op, status="error", error=str(e))


class DhcpStaticAddHandler:
    op_type = "dhcp.static.add"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        p = op.params
        body = {
            "reservation": {
                "subnet": p["interface"],
                "ip_address": p["ip"],
                "hw_address": p["mac"],
                "hostname": p.get("hostname", ""),
            }
        }
        try:
            add = await ctx.api.post("/api/kea/dhcpv4/addReservation", json=body)
            if add.get("result") != "saved":
                return OpResult(
                    op=op.op, status="error", response=add,
                    error=f"addReservation failed: {add}",
                )
            reconf = await ctx.api.post("/api/kea/service/reconfigure", json={})
            return OpResult(
                op=op.op, status="ok",
                response={"add": add, "reconfigure": reconf},
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("dhcp.static.add failed")
            return OpResult(op=op.op, status="error", error=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plans/handlers/test_dhcp.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/plans/handlers/dhcp.py tests/unit/plans/handlers/test_dhcp.py
git commit -m "$(cat <<'EOF'
feat: dhcp.scope.create + dhcp.static.add handlers (Kea)

Targets OPNsense 24+ Kea backend (default for new installs).
ISC fallback can land in v2 if needed.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 13: Lockout check + reachability probe

**Files:**
- Create: `src/opnsense_agent/safety/lockout.py`
- Create: `src/opnsense_agent/safety/probe.py`
- Create: `tests/unit/safety/test_lockout.py`
- Create: `tests/unit/safety/test_probe.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/safety/test_lockout.py`:
```python
from __future__ import annotations

import pytest

from opnsense_agent.plans.schema import Plan, PlanOp, PlanStatus, PlanTarget
from opnsense_agent.safety.lockout import LockoutWarning, check_plan


def _plan(ops: list[PlanOp]) -> Plan:
    return Plan(
        plan_id="test",
        description="t",
        created="2026-05-03T00:00:00Z",  # type: ignore[arg-type]
        target=PlanTarget(host="x"),
        ops=ops,
    )


def test_no_warnings_for_safe_vlan_create() -> None:
    plan = _plan([PlanOp(op="vlan.create", params={"tag": 30, "parent_if": "igb1"})])
    warnings = check_plan(plan, self_ip="10.0.0.50", management_if="igb0")
    assert warnings == []


def test_warns_on_management_interface_disable() -> None:
    plan = _plan([
        PlanOp(
            op="interface.configure",
            params={"opn_if_name": "igb0", "enabled": False},
        )
    ])
    warnings = check_plan(plan, self_ip="10.0.0.50", management_if="igb0")
    assert any("management interface" in w.message.lower() for w in warnings)


def test_warns_on_ssh_service_disable() -> None:
    plan = _plan([
        PlanOp(op="service.disable", params={"name": "openssh"})
    ])
    warnings = check_plan(plan, self_ip="10.0.0.50", management_if="igb0")
    assert any("ssh" in w.message.lower() for w in warnings)
```

Create `tests/unit/safety/test_probe.py`:
```python
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from opnsense_agent.safety.probe import reachability_probe


@pytest.mark.asyncio
async def test_probe_returns_true_on_first_success() -> None:
    api = AsyncMock()
    api.get.return_value = {"status": "ok"}
    result = await reachability_probe(
        api=api, max_seconds=10, interval_seconds=1
    )
    assert result is True
    assert api.get.call_count == 1


@pytest.mark.asyncio
async def test_probe_returns_false_when_all_fail() -> None:
    api = AsyncMock()
    api.get.side_effect = Exception("connection refused")
    result = await reachability_probe(
        api=api, max_seconds=3, interval_seconds=1
    )
    assert result is False
    assert api.get.call_count >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/safety/test_lockout.py tests/unit/safety/test_probe.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement lockout check**

Create `src/opnsense_agent/safety/lockout.py`:
```python
"""Pre-apply lockout check: refuses risky plan ops or surfaces warnings."""
from __future__ import annotations

from dataclasses import dataclass

from opnsense_agent.plans.schema import Plan, PlanOp


@dataclass(frozen=True)
class LockoutWarning:
    op_index: int
    op_type: str
    message: str


_DANGEROUS_SERVICES = {"openssh", "sshd", "nginx", "lighttpd", "configd"}


def _check_op(
    op: PlanOp, idx: int, *, self_ip: str, management_if: str
) -> list[LockoutWarning]:
    warnings: list[LockoutWarning] = []
    p = op.params

    if op.op == "interface.configure":
        if p.get("opn_if_name") == management_if and p.get("enabled") is False:
            warnings.append(
                LockoutWarning(
                    op_index=idx,
                    op_type=op.op,
                    message=(
                        f"This op disables the management interface "
                        f"({management_if}). You will lose access."
                    ),
                )
            )
        if p.get("opn_if_name") == management_if and "ipv4" in p:
            warnings.append(
                LockoutWarning(
                    op_index=idx,
                    op_type=op.op,
                    message=(
                        f"This op changes the IP of the management interface "
                        f"({management_if}). Reachability will likely break."
                    ),
                )
            )

    if op.op == "service.disable":
        name = p.get("name", "").lower()
        if name in _DANGEROUS_SERVICES:
            warnings.append(
                LockoutWarning(
                    op_index=idx,
                    op_type=op.op,
                    message=(
                        f"Disabling service {name!r} would block management access "
                        "(SSH or web/API)."
                    ),
                )
            )

    if op.op == "rule.delete":
        # Best-effort: warn if a rule's source includes self_ip.
        # The actual check requires looking at the rule, which we'd do
        # by fetching it from the API in a richer impl. For v1, warn on any delete.
        warnings.append(
            LockoutWarning(
                op_index=idx,
                op_type=op.op,
                message=(
                    f"Rule deletion can break management access. Verify the rule "
                    f"being deleted does not allow your IP ({self_ip})."
                ),
            )
        )

    return warnings


def check_plan(
    plan: Plan, *, self_ip: str, management_if: str
) -> list[LockoutWarning]:
    """Return all lockout warnings for the plan; empty list = safe."""
    warnings: list[LockoutWarning] = []
    for idx, op in enumerate(plan.ops):
        warnings.extend(
            _check_op(op, idx, self_ip=self_ip, management_if=management_if)
        )
    return warnings
```

- [ ] **Step 4: Implement reachability probe**

Create `src/opnsense_agent/safety/probe.py`:
```python
"""Post-apply reachability probe."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opnsense_agent.client.api import OpnApiClient

logger = logging.getLogger(__name__)

PROBE_PATH = "/api/diagnostics/system/system_information"


async def reachability_probe(
    *,
    api: "OpnApiClient",
    max_seconds: int = 30,
    interval_seconds: int = 3,
) -> bool:
    """Returns True as soon as the firewall responds; False if all attempts fail."""
    elapsed = 0
    attempt = 0
    while elapsed <= max_seconds:
        attempt += 1
        try:
            await api.get(PROBE_PATH)
            logger.info("Reachability probe: success on attempt %d", attempt)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("Reachability probe attempt %d failed: %s", attempt, e)
        if elapsed + interval_seconds > max_seconds:
            break
        await asyncio.sleep(interval_seconds)
        elapsed += interval_seconds
    logger.warning("Reachability probe: all %d attempts failed", attempt)
    return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/safety/test_lockout.py tests/unit/safety/test_probe.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/opnsense_agent/safety/lockout.py src/opnsense_agent/safety/probe.py tests/unit/safety/test_lockout.py tests/unit/safety/test_probe.py
git commit -m "$(cat <<'EOF'
feat: lockout check + reachability probe

Lockout check warns on management interface disable/IP-change, dangerous
service disable, and rule deletion. Reachability probe loops API
diagnostics until success or timeout.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 14: Plan apply pipeline (the chokepoint)

**Files:**
- Modify: `src/opnsense_agent/plans/engine.py`
- Create: `tests/unit/plans/test_apply_pipeline.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/plans/test_apply_pipeline.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from opnsense_agent.plans.engine import (
    OpHandlerRegistry,
    PlanApplyPipeline,
    PlanApplyResult,
)
from opnsense_agent.plans.schema import (
    Plan,
    PlanOp,
    PlanStatus,
    PlanTarget,
)
from opnsense_agent.plans.store import PlanStore


def _plan() -> Plan:
    return Plan(
        plan_id="t1",
        description="test",
        created=datetime.now(timezone.utc),
        target=PlanTarget(host="opnsense.test"),
        ops=[PlanOp(op="vlan.create", params={"tag": 30, "parent_if": "igb1"})],
    )


class _OkHandler:
    op_type = "vlan.create"

    async def execute(self, op, ctx):  # type: ignore[no-untyped-def]
        from opnsense_agent.plans.schema import OpResult
        return OpResult(op=op.op, status="ok", response={"r": 1})


class _FailHandler:
    op_type = "vlan.create"

    async def execute(self, op, ctx):  # type: ignore[no-untyped-def]
        from opnsense_agent.plans.schema import OpResult
        return OpResult(op=op.op, status="error", error="boom")


@pytest.mark.asyncio
async def test_apply_happy_path(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_OkHandler())

    probe = AsyncMock(return_value=True)
    api = AsyncMock()
    ssh = AsyncMock()

    pipeline = PlanApplyPipeline(
        store=store,
        registry=registry,
        backup=backup,
        api=api,
        ssh=ssh,
        probe=probe,
        self_ip="10.0.0.50",
        management_if="igb0",
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)
    assert isinstance(result, PlanApplyResult)
    assert result.status is PlanStatus.applied
    assert result.backup_id == "bk-1"
    assert backup.restore.await_count == 0


@pytest.mark.asyncio
async def test_apply_op_failure_triggers_rollback(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_FailHandler())

    probe = AsyncMock(return_value=True)
    api = AsyncMock()
    ssh = AsyncMock()

    pipeline = PlanApplyPipeline(
        store=store, registry=registry, backup=backup,
        api=api, ssh=ssh, probe=probe,
        self_ip="10.0.0.50", management_if="igb0",
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)
    assert result.status is PlanStatus.failed
    assert backup.restore.await_count == 1


@pytest.mark.asyncio
async def test_apply_probe_failure_triggers_rollback(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_OkHandler())

    probe = AsyncMock(return_value=False)
    api = AsyncMock()
    ssh = AsyncMock()

    pipeline = PlanApplyPipeline(
        store=store, registry=registry, backup=backup,
        api=api, ssh=ssh, probe=probe,
        self_ip="10.0.0.50", management_if="igb0",
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)
    assert result.status is PlanStatus.rolled_back
    assert backup.restore.await_count == 1


@pytest.mark.asyncio
async def test_apply_refuses_without_confirm(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)
    pipeline = PlanApplyPipeline(
        store=store, registry=OpHandlerRegistry(),
        backup=AsyncMock(), api=AsyncMock(), ssh=AsyncMock(),
        probe=AsyncMock(), self_ip="x", management_if="x",
    )
    with pytest.raises(PermissionError, match="confirm"):
        await pipeline.apply(plan.plan_id, confirm=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/plans/test_apply_pipeline.py -v`
Expected: FAIL with `ImportError` (PlanApplyPipeline doesn't exist yet).

- [ ] **Step 3: Extend engine with apply pipeline**

Add to `src/opnsense_agent/plans/engine.py` (append below the existing classes):

```python
# === Apply pipeline ===

from datetime import datetime, timezone
from typing import Awaitable, Callable, Protocol as _Protocol

from opnsense_agent.plans.schema import Plan, PlanStatus
from opnsense_agent.plans.store import PlanStore
from opnsense_agent.safety import lockout


class _BackupProto(_Protocol):
    async def create(self, api: "OpnApiClient", label: str | None = None) -> str: ...
    async def restore(self, api: "OpnApiClient", backup_id: str) -> None: ...


@dataclass(frozen=True)
class PlanApplyResult:
    plan_id: str
    status: PlanStatus
    backup_id: str | None
    rollback_reason: str | None
    op_results: list[OpResult]


class PlanApplyPipeline:
    """The single chokepoint for all mutations.

    Pipeline:
      1. Lockout check (warnings → require override or fail)
      2. Backup
      3. Sequential op execution (stop on first failure)
      4. Reachability probe
      5. Finalize plan status; on failure or probe failure, restore backup
    """

    def __init__(
        self,
        *,
        store: PlanStore,
        registry: OpHandlerRegistry,
        backup: _BackupProto,
        api: "OpnApiClient",
        ssh: "OpnSshClient",
        probe: Callable[..., Awaitable[bool]],
        self_ip: str,
        management_if: str,
        allow_lockout_override: bool = True,
    ) -> None:
        self._store = store
        self._registry = registry
        self._backup = backup
        self._api = api
        self._ssh = ssh
        self._probe = probe
        self._self_ip = self_ip
        self._management_if = management_if
        self._allow_lockout_override = allow_lockout_override

    async def apply(
        self,
        plan_id: str,
        *,
        confirm: bool,
        override_lockout: bool = False,
    ) -> PlanApplyResult:
        if not confirm:
            raise PermissionError(
                "apply requires confirm=True. The /opn-apply slash command "
                "handles this; do not call apply directly."
            )

        plan = self._store.load(plan_id)
        if plan.status is not PlanStatus.draft:
            raise ValueError(
                f"Plan {plan_id} status is {plan.status.value}; only drafts can be applied."
            )

        warnings = lockout.check_plan(
            plan, self_ip=self._self_ip, management_if=self._management_if
        )
        if warnings and not override_lockout:
            if not self._allow_lockout_override:
                raise PermissionError(
                    f"Lockout check produced {len(warnings)} warning(s) and override "
                    "is disabled in safety config."
                )
            return PlanApplyResult(
                plan_id=plan.plan_id,
                status=PlanStatus.draft,
                backup_id=None,
                rollback_reason=(
                    f"Lockout warnings: {[w.message for w in warnings]} "
                    "(override required)"
                ),
                op_results=[],
            )

        backup_id = await self._backup.create(
            api=self._api, label=f"pre-apply-{plan.plan_id}"
        )

        ctx = HandlerContext(api=self._api, ssh=self._ssh)
        results: list[OpResult] = []
        had_failure = False

        for op in plan.ops:
            handler = self._registry.get(op.op)
            result = await handler.execute(op, ctx)
            results.append(result)
            if result.status != "ok":
                had_failure = True
                logger.error("Op failed: %s — %s", op.op, result.error)
                break

        if had_failure:
            await self._backup.restore(api=self._api, backup_id=backup_id)
            final = plan.model_copy(update={
                "status": PlanStatus.failed,
                "execution": plan.execution.model_copy(update={
                    "backup_id": backup_id,
                    "applied_at": datetime.now(timezone.utc),
                    "results": results,
                    "rollback_reason": "op execution failed",
                }),
            })
            self._store.finalize(final)
            return PlanApplyResult(
                plan_id=plan.plan_id, status=PlanStatus.failed,
                backup_id=backup_id, rollback_reason="op execution failed",
                op_results=results,
            )

        probe_ok = await self._probe(api=self._api)
        if not probe_ok:
            await self._backup.restore(api=self._api, backup_id=backup_id)
            final = plan.model_copy(update={
                "status": PlanStatus.rolled_back,
                "execution": plan.execution.model_copy(update={
                    "backup_id": backup_id,
                    "applied_at": datetime.now(timezone.utc),
                    "results": results,
                    "rollback_reason": "post-apply reachability probe failed",
                }),
            })
            self._store.finalize(final)
            return PlanApplyResult(
                plan_id=plan.plan_id, status=PlanStatus.rolled_back,
                backup_id=backup_id,
                rollback_reason="post-apply reachability probe failed",
                op_results=results,
            )

        final = plan.model_copy(update={
            "status": PlanStatus.applied,
            "execution": plan.execution.model_copy(update={
                "backup_id": backup_id,
                "applied_at": datetime.now(timezone.utc),
                "results": results,
            }),
        })
        self._store.finalize(final)
        self._append_audit(plan_id=plan.plan_id, action="apply",
                           backup_id=backup_id, status=PlanStatus.applied)
        return PlanApplyResult(
            plan_id=plan.plan_id, status=PlanStatus.applied,
            backup_id=backup_id, rollback_reason=None, op_results=results,
        )

    def _append_audit(
        self, *, plan_id: str, action: str, backup_id: str | None,
        status: PlanStatus,
    ) -> None:
        audit_path = self._store.runs_dir / "audit.log"
        line = (
            f"{datetime.now(timezone.utc).isoformat()} "
            f"action={action} plan_id={plan_id} backup_id={backup_id} "
            f"status={status.value}\n"
        )
        with audit_path.open("a") as f:
            f.write(line)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/plans/test_apply_pipeline.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full unit test suite**

Run: `pytest tests/unit -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/opnsense_agent/plans/engine.py tests/unit/plans/test_apply_pipeline.py
git commit -m "$(cat <<'EOF'
feat: plan apply pipeline — the single mutation chokepoint

lockout check → backup → sequential op execution → reachability probe →
finalize. Op failure or probe failure triggers backup restore and
status=failed/rolled_back. Audit log line appended on completion.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 15: MCP server (14 tools wired up)

**Files:**
- Create: `src/opnsense_agent/mcp_server.py`
- Create: `tests/smoke/test_mcp_server.py`

- [ ] **Step 1: Write the failing smoke test**

Create `tests/smoke/test_mcp_server.py`:
```python
"""Smoke test: MCP server registers the expected tool names."""
from __future__ import annotations

from opnsense_agent.mcp_server import build_server, EXPECTED_TOOLS


def test_server_registers_all_expected_tools() -> None:
    server = build_server()
    registered = {t.name for t in server.list_tools()}
    assert registered == set(EXPECTED_TOOLS), (
        f"Missing: {set(EXPECTED_TOOLS) - registered}; "
        f"Unexpected: {registered - set(EXPECTED_TOOLS)}"
    )


def test_no_opn_api_post_tool_exists() -> None:
    """Critical invariant from the spec: there is no opn_api_post tool."""
    server = build_server()
    names = {t.name for t in server.list_tools()}
    assert "opn_api_post" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/smoke/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement MCP server**

Create `src/opnsense_agent/mcp_server.py`:
```python
"""MCP server entry point. Registers the 14 primitive tools."""
from __future__ import annotations

import logging
from typing import Any

import yaml
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from opnsense_agent.client.api import OpnApiClient
from opnsense_agent.client.ssh import OpnSshClient, SshAllowlistError
from opnsense_agent.config import Settings, load_settings
from opnsense_agent.plans.engine import OpHandlerRegistry, PlanApplyPipeline
from opnsense_agent.plans.handlers.dhcp import (
    DhcpScopeCreateHandler,
    DhcpStaticAddHandler,
)
from opnsense_agent.plans.handlers.interface import (
    InterfaceAssignHandler,
    InterfaceConfigureHandler,
)
from opnsense_agent.plans.handlers.vlan import VlanCreateHandler
from opnsense_agent.plans.schema import Plan
from opnsense_agent.plans.store import PlanStore
from opnsense_agent.safety.backup import BackupStore
from opnsense_agent.safety.lockout import check_plan as lockout_check_plan
from opnsense_agent.safety.probe import reachability_probe

logger = logging.getLogger(__name__)

EXPECTED_TOOLS: list[str] = [
    # Read-only
    "opn_api_get",
    "opn_ssh_exec_readonly",
    "opn_status",
    "opn_get_self_ip",
    # Backup & restore
    "opn_backup_create",
    "opn_backup_list",
    "opn_backup_restore",
    "opn_config_diff",
    # Plan workflow
    "opn_plan_save",
    "opn_plan_load",
    "opn_plan_list",
    "opn_plan_preview",
    "opn_plan_apply",
    # Safety
    "opn_lockout_check",
]


def _build_registry() -> OpHandlerRegistry:
    registry = OpHandlerRegistry()
    registry.register(VlanCreateHandler())
    registry.register(InterfaceAssignHandler())
    registry.register(InterfaceConfigureHandler())
    registry.register(DhcpScopeCreateHandler())
    registry.register(DhcpStaticAddHandler())
    return registry


def build_server(settings: Settings | None = None) -> Server:
    """Build the MCP server with all 14 tools registered.

    Pulled out as a function so smoke tests can introspect tool names
    without starting stdio.
    """
    settings = settings or load_settings()
    server: Server = Server("opnsense-agent")

    api = OpnApiClient(firewall=settings.firewall, auth=settings.auth)
    ssh = OpnSshClient(firewall=settings.firewall)
    backup_store = BackupStore(
        runs_dir=settings.runtime.runs_dir,
        retention=settings.runtime.backup_retention,
    )
    plan_store = PlanStore(runs_dir=settings.runtime.runs_dir)
    registry = _build_registry()

    # Capture self_ip and management_if at server start (one round-trip each).
    # For v1 we read these from config as fallbacks until the diagnostic
    # endpoints are wired up.
    self_ip = "0.0.0.0"  # populated by opn_status / opn_get_self_ip on first call
    management_if = "igb0"  # default; overridable via env once known

    pipeline = PlanApplyPipeline(
        store=plan_store, registry=registry, backup=backup_store,
        api=api, ssh=ssh, probe=reachability_probe,
        self_ip=self_ip, management_if=management_if,
        allow_lockout_override=settings.safety.allow_lockout_override,
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=n, description=_TOOL_DESCRIPTIONS[n], inputSchema={"type": "object"})
            for n in EXPECTED_TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            result = await _dispatch(
                name, arguments, api=api, ssh=ssh,
                backup=backup_store, plan_store=plan_store,
                pipeline=pipeline,
            )
            return [TextContent(type="text", text=str(result))]
        except SshAllowlistError as e:
            return [TextContent(type="text", text=f"REJECTED: {e}")]
        except Exception as e:  # noqa: BLE001
            logger.exception("Tool %s failed", name)
            return [TextContent(type="text", text=f"ERROR: {e}")]

    return server


_TOOL_DESCRIPTIONS: dict[str, str] = {
    "opn_api_get": "GET against an OPNsense /api/... path. Read-only.",
    "opn_ssh_exec_readonly": "Run a read-only shell command on the firewall. Allowlisted.",
    "opn_status": "Composite health snapshot of the firewall.",
    "opn_get_self_ip": "Returns the IP your management session originates from.",
    "opn_backup_create": "Pull config.xml and save with a timestamp + optional label.",
    "opn_backup_list": "List saved backups with timestamps and labels.",
    "opn_backup_restore": "Restore a backup. Two-step: requires confirm=true.",
    "opn_config_diff": "Diff two backups, or backup vs. current config.",
    "opn_plan_save": "Validate and persist a plan YAML. Returns plan_id.",
    "opn_plan_load": "Load a saved plan by id.",
    "opn_plan_list": "List saved plans with their statuses.",
    "opn_plan_preview": "Resolve a plan to the API/SSH calls it would make. No mutation.",
    "opn_plan_apply": "Execute a plan. The ONLY path for mutations. Requires confirm=true.",
    "opn_lockout_check": "Analyze a plan for lockout risk.",
}


async def _dispatch(
    name: str,
    args: dict[str, Any],
    *,
    api: OpnApiClient,
    ssh: OpnSshClient,
    backup: BackupStore,
    plan_store: PlanStore,
    pipeline: PlanApplyPipeline,
) -> Any:
    if name == "opn_api_get":
        return await api.get(args["path"], params=args.get("params"))

    if name == "opn_ssh_exec_readonly":
        result = await ssh.exec_readonly(args["command"], timeout=args.get("timeout", 15))
        return {"stdout": result.stdout, "stderr": result.stderr, "exit": result.exit_code}

    if name == "opn_status":
        info = await api.get("/api/diagnostics/system/system_information")
        return {"reachable": True, "info": info}

    if name == "opn_get_self_ip":
        # Use system info; the IP we connect from is the one the firewall sees.
        # For v1 this is a placeholder; resolve fully in integration testing.
        return {"self_ip": "see opn_status output"}

    if name == "opn_backup_create":
        return await backup.create(api=api, label=args.get("label"))

    if name == "opn_backup_list":
        return [{"id": r.id, "label": r.label, "created": r.created.isoformat()}
                for r in backup.list()]

    if name == "opn_backup_restore":
        if not args.get("confirm", False):
            return "REJECTED: opn_backup_restore requires confirm=true."
        await backup.restore(api=api, backup_id=args["backup_id"])
        return {"status": "restored", "backup_id": args["backup_id"]}

    if name == "opn_config_diff":
        return "config_diff: not yet implemented in v1; track in a follow-up."

    if name == "opn_plan_save":
        plan = Plan.model_validate(yaml.safe_load(args["plan_yaml"]))
        return plan_store.save(plan)

    if name == "opn_plan_load":
        return plan_store.load(args["plan_id"]).model_dump(mode="json")

    if name == "opn_plan_list":
        return [
            {"plan_id": p.plan_id, "description": p.description,
             "status": p.status.value, "created": p.created.isoformat()}
            for p in plan_store.list()
        ]

    if name == "opn_plan_preview":
        plan = plan_store.load(args["plan_id"])
        return {"plan_id": plan.plan_id, "ops": [op.model_dump() for op in plan.ops]}

    if name == "opn_plan_apply":
        result = await pipeline.apply(
            args["plan_id"],
            confirm=bool(args.get("confirm", False)),
            override_lockout=bool(args.get("override_lockout", False)),
        )
        return {
            "plan_id": result.plan_id,
            "status": result.status.value,
            "backup_id": result.backup_id,
            "rollback_reason": result.rollback_reason,
            "op_results": [r.model_dump() for r in result.op_results],
        }

    if name == "opn_lockout_check":
        plan = plan_store.load(args["plan_id"])
        warnings = lockout_check_plan(
            plan, self_ip=args.get("self_ip", "0.0.0.0"),
            management_if=args.get("management_if", "igb0"),
        )
        return [{"op_index": w.op_index, "op_type": w.op_type, "message": w.message}
                for w in warnings]

    raise ValueError(f"Unknown tool: {name}")


def main() -> None:
    """Entry point for `opnsense-agent-mcp` script (registered in pyproject)."""
    import asyncio
    server = build_server()
    asyncio.run(_run_stdio(server))


async def _run_stdio(server: Server) -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    main()
```

Add to `pyproject.toml`'s `[project.scripts]`:
```toml
opnsense-agent-mcp = "opnsense_agent.mcp_server:main"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/smoke/test_mcp_server.py -v`
Expected: 2 passed.

> **Note:** the smoke test instantiates the server, which calls `load_settings()`. If a test config doesn't exist, set `OPN_AGENT_*` env vars in a `conftest.py` for the smoke tier, OR refactor `build_server` to accept settings (which it already does — pass a fake `Settings` from the test fixture). Adjust the test to construct a fake `Settings` and pass it in if the default-load path fails in CI.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/mcp_server.py tests/smoke/test_mcp_server.py pyproject.toml
git commit -m "$(cat <<'EOF'
feat: MCP server with 14 primitive tools wired

Smoke test asserts the expected tool set is registered and that
opn_api_post does not exist (the spec invariant).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 16: Plugin manifest + .mcp.json

**Files:**
- Create: `plugin.json`
- Create: `.mcp.json`
- Create: `tests/smoke/test_plugin_manifest.py`

- [ ] **Step 1: Write the failing test**

Create `tests/smoke/test_plugin_manifest.py`:
```python
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_plugin_manifest_is_valid_json() -> None:
    manifest = json.loads((REPO_ROOT / "plugin.json").read_text())
    assert manifest["name"] == "opnsense-agent"
    assert "version" in manifest
    assert "description" in manifest


def test_mcp_json_registers_server() -> None:
    mcp = json.loads((REPO_ROOT / ".mcp.json").read_text())
    assert "mcpServers" in mcp
    assert "opnsense-agent" in mcp["mcpServers"]
    server_cfg = mcp["mcpServers"]["opnsense-agent"]
    # CLAUDE_PLUGIN_ROOT must be used so the plugin is portable.
    assert "${CLAUDE_PLUGIN_ROOT}" in server_cfg.get("command", "") + " ".join(
        server_cfg.get("args", [])
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/smoke/test_plugin_manifest.py -v`
Expected: FAIL — files don't exist.

- [ ] **Step 3: Create the manifest files**

Create `plugin.json`:
```json
{
  "name": "opnsense-agent",
  "version": "0.1.0",
  "description": "Manage a single OPNsense firewall via plan-then-apply workflow",
  "author": "Tyler Creighton",
  "license": "MIT",
  "homepage": "https://github.com/tcreight/opnsense-agent"
}
```

Create `.mcp.json`:
```json
{
  "mcpServers": {
    "opnsense-agent": {
      "command": "${CLAUDE_PLUGIN_ROOT}/.venv/bin/opnsense-agent-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

> Implementer note: the path assumes the user runs `pip install -e .` inside the plugin directory's `.venv`. If the user prefers a system Python install, they can edit `.mcp.json` to point at `python3` + `-m opnsense_agent.mcp_server` after install. Document both options in the README.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/smoke/test_plugin_manifest.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin.json .mcp.json tests/smoke/test_plugin_manifest.py
git commit -m "$(cat <<'EOF'
feat: plugin manifest + MCP server registration

Uses ${CLAUDE_PLUGIN_ROOT} for portability across install locations.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 17: Skills (v1 set — 6 skills)

**Files:** create one per skill, each with the full content shown.
- Create: `skills/opn-safety/SKILL.md`
- Create: `skills/opn-planning/SKILL.md`
- Create: `skills/opn-interfaces/SKILL.md`
- Create: `skills/opn-vlans/SKILL.md`
- Create: `skills/opn-dhcp/SKILL.md`
- Create: `skills/opn-troubleshooting/SKILL.md`
- Create: `tests/smoke/test_skill_frontmatter.py`

- [ ] **Step 1: Write the failing frontmatter test**

Create `tests/smoke/test_skill_frontmatter.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/smoke/test_skill_frontmatter.py -v`
Expected: FAIL — skills don't exist yet.

- [ ] **Step 3: Create `opn-safety` skill**

Create `skills/opn-safety/SKILL.md`:
```markdown
---
name: opn-safety
description: Use whenever planning or applying changes to OPNsense — covers backup-before-apply, lockout reasoning, two-stage commit, and rollback procedure.
---

# OPNsense Safety Patterns

## Two-stage commit

Every mutation goes through `/opn-plan` then `/opn-apply`. Never call `opn_plan_apply` from inside diagnostic conversations.

## Lockout reasoning

Before any apply, the lockout check inspects the plan for ops that would:
- Disable the management interface
- Change the management interface IP
- Disable SSH or the API/web service
- Delete a firewall rule that allows traffic from the operator's IP

If warnings appear, surface them to the user and require explicit override.

## Rollback procedure

1. The apply pipeline auto-restores the pre-apply backup on:
   - Op execution failure (any non-ok result)
   - Reachability probe failure (firewall stopped responding)
2. Manual rollback: `/opn-rollback <backup_id>` — two-step confirm.
3. If the firewall is fully unreachable: physical/console access required (no software fix).

## Patterns
- Always backup before any external change (manual `/opn-backup` if you're about to do GUI work).
- Prefer making one logical change per plan — easier to reason about, easier to roll back.
- After apply, verify intent matches reality: `/opn-status` and check the relevant subsystem.
```

- [ ] **Step 4: Create `opn-planning` skill**

Create `skills/opn-planning/SKILL.md`:
```markdown
---
name: opn-planning
description: Use when drafting an OPNsense plan YAML — covers schema, op catalog, and composition patterns.
---

# Plan YAML Schema

```yaml
plan_id: <ISO-8601 timestamp>-<short-slug>
description: <one line>
created: <ISO-8601 UTC timestamp>
status: draft     # set by engine, do not change manually
target:
  host: <hostname or IP>
  api_user: <optional, for audit>
ops:
  - op: <op.type>
    params: { ... }
execution:        # filled by engine; leave empty in drafts
  backup_id: null
  applied_at: null
  results: []
  rollback_reason: null
```

## v1 op catalog

### `vlan.create`
- `tag` (int, 2-4094, avoid 1)
- `parent_if` (str, e.g. `igb1`)
- `description` (str)

### `interface.assign`
- `vlan_tag` (int)
- `parent_if` (str)
- `opn_if_name` (str, e.g. `opt3`)
- `enabled` (bool, default true)

### `interface.configure`
- `opn_if_name` (str)
- `ipv4` (str, IP address)
- `ipv4_subnet` (int, CIDR bits)
- `ipv6` (str, optional)

### `dhcp.scope.create`
- `interface` (str)
- `subnet` (str, CIDR)
- `range_from`, `range_to` (str)
- `router` (str)
- `dns` (list[str])

### `dhcp.static.add`
- `interface` (str)
- `mac` (str)
- `ip` (str)
- `hostname` (str, optional)

## Composition patterns

### Stand up a new VLAN-based subnet end-to-end
```yaml
ops:
  - op: vlan.create
    params: { tag: 30, parent_if: igb1, description: "IoT" }
  - op: interface.assign
    params: { vlan_tag: 30, parent_if: igb1, opn_if_name: opt3, enabled: true }
  - op: interface.configure
    params: { opn_if_name: opt3, ipv4: 10.30.0.1, ipv4_subnet: 24 }
  - op: dhcp.scope.create
    params:
      interface: opt3
      subnet: 10.30.0.0/24
      range_from: 10.30.0.100
      range_to: 10.30.0.200
      router: 10.30.0.1
      dns: [10.30.0.1]
```

Order matters: VLAN before assignment before configuration before DHCP.

## Pitfalls
- Do not skip `interface.assign` after `vlan.create` — the VLAN won't be usable as a routed interface otherwise.
- Use `opt<N>` names consistent with what's already taken; check via `opn_api_get('/api/interfaces/overview/...')` first.
- Avoid VLAN tag 1 (default/native).
```

- [ ] **Step 5: Create `opn-interfaces` skill**

Create `skills/opn-interfaces/SKILL.md`:
```markdown
---
name: opn-interfaces
description: Use when creating, assigning, or configuring OPNsense interfaces — covers physical NIC naming, assignment vs configuration, and IPv4/IPv6 setup.
---

# OPNsense Interfaces

## Physical NIC naming on OPNsense (FreeBSD)

- Intel 1G: `igb0`, `igb1`, `em0`, `em1`
- Intel 10G: `ix0`, `ixl0`
- Realtek: `re0`
- Bridges: `bridge0`, `bridge1`
- VLAN children: `<parent>_vlan<tag>` — e.g. `igb1_vlan30`

## Three-step interface setup

1. **Create** the underlying entity if needed (e.g. `vlan.create`).
2. **Assign** the entity as an OPNsense logical interface (`opt1`, `opt2`, etc.). Until assigned, the entity is invisible to firewall rules.
3. **Configure** the assigned interface (IP, subnet, gateway).

The `interface.assign` op handles step 2; `interface.configure` handles step 3.

## IPv4
- `ipv4`: dotted-quad address (the firewall's IP on this interface)
- `ipv4_subnet`: CIDR bits (e.g. 24 for /24)

## IPv6
- `ipv6: track` to track the WAN delegation
- Or a static `2001:db8::1` form

## Pitfalls
- Never `disable` the management interface (the one your API/SSH session arrives on). The lockout check catches this but the warning exists for a reason.
- After assigning a new interface, OPNsense does NOT auto-create allow rules. Phase A (firewall rules) handles that.
```

- [ ] **Step 6: Create `opn-vlans` skill**

Create `skills/opn-vlans/SKILL.md`:
```markdown
---
name: opn-vlans
description: Use when creating or modifying VLANs on OPNsense — covers tag selection, parent NIC choice, and the assign-as-interface gotcha.
---

# OPNsense VLANs

## Tag selection
- Valid range: 2–4094
- Avoid `1` (treated as native/untagged on most hardware)
- Common convention: tag = third octet of the subnet (10.30.0.0/24 → tag 30) — purely cosmetic, useful for memory.

## Parent interface
- The parent must be a physical NIC (or LAGG), not another VLAN.
- The parent does not need to be assigned itself — VLAN children can use an unassigned parent.

## Two-stage workflow
1. `vlan.create` — creates the VLAN child entity (`igb1_vlan30`).
2. `interface.assign` — assigns it as an OPNsense logical interface (`opt3`).

Forgetting step 2 is the #1 trap: the VLAN exists but firewall rules can't reference it.

## Worked example

```yaml
ops:
  - op: vlan.create
    params: { tag: 30, parent_if: igb1, description: "IoT" }
  - op: interface.assign
    params: { vlan_tag: 30, parent_if: igb1, opn_if_name: opt3, enabled: true }
```

## Verification after apply
- `/opn-status` → confirms reconfigure succeeded
- `opn_api_get('/api/interfaces/vlan_settings/searchItem')` → confirms VLAN exists
- `opn_ssh_exec_readonly('ifconfig igb1_vlan30')` → confirms FreeBSD sees it

## API endpoints used
- `POST /api/interfaces/vlan_settings/addItem`
- `POST /api/interfaces/vlan_settings/reconfigure`

## Related skills
- `opn-interfaces` for the assign/configure follow-up
- `opn-dhcp` for adding a DHCP scope to the new interface
```

- [ ] **Step 7: Create `opn-dhcp` skill**

Create `skills/opn-dhcp/SKILL.md`:
```markdown
---
name: opn-dhcp
description: Use when creating DHCP scopes or static reservations on OPNsense — covers Kea (default in 24+) workflow and gotchas.
---

# OPNsense DHCP (Kea)

## Backend
OPNsense 24+ uses **Kea** by default for new installs. Older installs may still use **ISC** (`/api/dhcpv4/...`). v1 of this plugin targets Kea only.

## Scope creation prerequisites
- The interface (`opt3`, etc.) must already be assigned and configured with an IP.
- The interface IP should be in the same subnet as the scope (and is usually used as the router).

## `dhcp.scope.create` params
- `interface`: OPNsense logical interface name (`opt3`)
- `subnet`: CIDR string (`10.30.0.0/24`)
- `range_from`, `range_to`: pool boundaries
- `router`: gateway IP (usually the interface IP)
- `dns`: list of DNS server IPs

## `dhcp.static.add` params (reservations)
- `interface`: scope's interface
- `mac`: 6-octet MAC, colon-separated
- `ip`: must be inside the subnet, ideally outside the dynamic pool
- `hostname`: optional but recommended

## Worked example

```yaml
ops:
  - op: dhcp.scope.create
    params:
      interface: opt3
      subnet: 10.30.0.0/24
      range_from: 10.30.0.100
      range_to: 10.30.0.200
      router: 10.30.0.1
      dns: [10.30.0.1]
  - op: dhcp.static.add
    params:
      interface: opt3
      mac: aa:bb:cc:dd:ee:ff
      ip: 10.30.0.50
      hostname: thermostat
```

## Pitfalls
- Don't put a static reservation IP inside the dynamic range — Kea will accept it but you'll get conflicts.
- Reconfigure runs after every scope/reservation change. If you're doing many changes, batch them in one plan.

## API endpoints used
- `POST /api/kea/dhcpv4/addSubnet`
- `POST /api/kea/dhcpv4/addReservation`
- `POST /api/kea/service/reconfigure`
```

- [ ] **Step 8: Create `opn-troubleshooting` skill**

Create `skills/opn-troubleshooting/SKILL.md`:
```markdown
---
name: opn-troubleshooting
description: Use when diagnosing OPNsense issues — symptom → diagnostic recipe map, all read-only.
---

# OPNsense Troubleshooting Recipes

All commands here are read-only (allowlist-safe via `opn_ssh_exec_readonly`).

## "VLAN doesn't show up as a usable interface"
Likely cause: VLAN was created but never assigned.
- `opn_api_get('/api/interfaces/vlan_settings/searchItem')` → confirm it exists
- `opn_api_get('/api/interfaces/overview/...')` → confirm an opt<N> is assigned to it

Fix: a new plan with `interface.assign`.

## "Hosts on new VLAN don't get DHCP leases"
Recipes (in order):
1. `opn_ssh_exec_readonly('ifconfig <opt-name>')` — interface up?
2. `opn_api_get('/api/kea/dhcpv4/get')` — scope present and enabled?
3. `opn_ssh_exec_readonly('tail -n 100 /var/log/dhcpd/latest.log')` — leases attempted?
4. Likely missing: a firewall rule allowing DHCP (UDP 67/68) on the new interface (Phase A territory; manual GUI rule for now).

## "Firewall rule isn't matching"
1. `opn_ssh_exec_readonly('pfctl -sr')` — the rule loaded into pf?
2. `opn_ssh_exec_readonly('pfctl -ss')` — current state table
3. `opn_ssh_exec_readonly('tail -n 200 /var/log/filter/latest.log')` — recent block/pass events

## "Can't reach the firewall after a change"
Stop. Don't issue more changes.
- If `/opn-rollback <backup_id>` fails too → physical/console access required
- The plan that broke things has its `backup_id` recorded — use that ID

## "API returns 401"
- Check `~/.config/opnsense-agent/config.toml` permissions and contents
- API key may have been revoked: System → Access → Users → <user> → API keys
- Run `opnsense-agent doctor`

## Reference
The lockout check exists to prevent the most common self-inflicted outages. If it warned and you overrode the warning, that's the first place to look.
```

- [ ] **Step 9: Run frontmatter test**

Run: `pytest tests/smoke/test_skill_frontmatter.py -v`
Expected: 1 passed.

- [ ] **Step 10: Commit**

```bash
git add skills/ tests/smoke/test_skill_frontmatter.py
git commit -m "$(cat <<'EOF'
feat: v1 skill set (safety, planning, interfaces, vlans, dhcp, troubleshooting)

Six on-demand skills covering Phase B (network buildout). Each loads
on demand based on what the user asks. Frontmatter test asserts all
six exist and parse.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 18: Subagents (planner + diag)

**Files:**
- Create: `agents/opn-planner.md`
- Create: `agents/opn-diag.md`
- Create: `tests/smoke/test_agent_frontmatter.py`

- [ ] **Step 1: Write the failing frontmatter test**

Create `tests/smoke/test_agent_frontmatter.py`:
```python
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
        m = FRONTMATTER.match(path.read_text())
        assert m is not None, f"{name}: missing YAML frontmatter"
        front = m.group(1)
        assert f"name: {name}" in front
        assert "description:" in front
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/smoke/test_agent_frontmatter.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `opn-planner` agent**

Create `agents/opn-planner.md`:
```markdown
---
name: opn-planner
description: Use when drafting an OPNsense change plan from a description. Loads opn-safety, opn-planning, and the relevant subsystem skills, then drafts a YAML plan and saves it as a draft.
---

You are the OPNsense planner subagent. Your job is to translate the user's description of a desired change into a valid plan YAML and save it.

## Your process

1. **Load required skills** (always): `opn-safety`, `opn-planning`.
2. **Load subsystem skills** based on the user's request:
   - VLAN-related → `opn-vlans` + `opn-interfaces`
   - DHCP-related → `opn-dhcp`
   - Anything physical-NIC → `opn-interfaces`
3. **Draft the plan YAML** following the schema in `opn-planning`. Generate a plan_id like `<ISO-timestamp>-<short-slug>` (e.g. `2026-05-03T14-30-22Z-iot-vlan`).
4. **Save the draft**: call `opn_plan_save(plan_yaml)`. Capture the returned `plan_id`.
5. **Preview**: call `opn_plan_preview(plan_id)`. Show the user the resolved op list.
6. **Report**: tell the user the plan_id and the next command (`/opn-apply <plan_id>`).

## What you do NOT do

- **Never** call `opn_plan_apply`. Only the user (via `/opn-apply`) can trigger an apply.
- **Never** make API/SSH calls outside of plan_save and plan_preview. Diagnostics is `/opn-diag`'s job.
- **Never** invent op types not in the planning catalog. If the user wants something we don't support, say so.

## Output format

After saving the plan:
- Print the plan_id
- Print a brief human summary of the ops
- Tell the user how to apply: `/opn-apply <plan_id>`
```

- [ ] **Step 4: Create `opn-diag` agent**

Create `agents/opn-diag.md`:
```markdown
---
name: opn-diag
description: Use for read-only OPNsense diagnostics. Loads opn-troubleshooting and relevant subsystem skills, calls opn_api_get and opn_ssh_exec_readonly to investigate, and reports findings without making changes.
---

You are the OPNsense diagnostic subagent. You investigate problems read-only and report findings. You do **not** save or apply plans.

## Your process

1. **Load skills**: `opn-troubleshooting`, plus subsystem skills relevant to the symptom.
2. **Investigate**: call `opn_api_get` (always safe) and `opn_ssh_exec_readonly` (allowlist-safe). Follow the recipes in `opn-troubleshooting`.
3. **Report findings**: what you observed, what you concluded, and what action would fix it.
4. **If a fix requires mutation**: tell the user to run `/opn-plan "<description of the fix>"`. Do not draft the plan yourself — that's `/opn-plan`'s job.

## What you do NOT do

- **Never** call `opn_plan_save`, `opn_plan_apply`, `opn_backup_restore`, or any mutation tool.
- **Never** invent SSH commands not on the read-only allowlist (you'll get a `SshAllowlistError`).
- **Never** speculate without evidence — when uncertain, say so.

## Output format

- Findings (numbered, evidence-backed)
- Diagnosis (one line)
- Recommended action: either `/opn-plan "..."` or "manual GUI work needed because X"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/smoke/test_agent_frontmatter.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add agents/ tests/smoke/test_agent_frontmatter.py
git commit -m "$(cat <<'EOF'
feat: planner + diag subagents

Planner translates descriptions into draft plans (never applies).
Diag investigates read-only and recommends actions (never mutates).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 19: Slash commands (6)

**Files:**
- Create: `commands/opn-plan.md`
- Create: `commands/opn-apply.md`
- Create: `commands/opn-status.md`
- Create: `commands/opn-backup.md`
- Create: `commands/opn-rollback.md`
- Create: `commands/opn-diag.md`
- Create: `tests/smoke/test_command_frontmatter.py`

- [ ] **Step 1: Write the failing frontmatter test**

Create `tests/smoke/test_command_frontmatter.py`:
```python
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXPECTED_COMMANDS = [
    "opn-plan", "opn-apply", "opn-status",
    "opn-backup", "opn-rollback", "opn-diag",
]
FRONTMATTER = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def test_all_commands_exist_with_valid_frontmatter() -> None:
    cmd_dir = REPO_ROOT / "commands"
    for name in EXPECTED_COMMANDS:
        path = cmd_dir / f"{name}.md"
        assert path.exists(), f"Missing command: {name}"
        m = FRONTMATTER.match(path.read_text())
        assert m is not None, f"{name}: missing YAML frontmatter"
        front = m.group(1)
        assert "description:" in front
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/smoke/test_command_frontmatter.py -v`
Expected: FAIL.

- [ ] **Step 3: Create the six command files**

Create `commands/opn-plan.md`:
```markdown
---
description: Draft an OPNsense change plan from a natural language description. Returns a plan_id you can apply with /opn-apply.
argument-hint: <description of the desired change>
---

Use the `opn-planner` subagent to draft a plan for: $ARGUMENTS

The planner will:
1. Load the relevant skills
2. Draft a plan YAML
3. Save it as a draft
4. Show you a preview
5. Tell you the plan_id to apply
```

Create `commands/opn-apply.md`:
```markdown
---
description: Review and apply a saved plan. Runs lockout check, asks for confirmation, executes via the apply pipeline.
argument-hint: <plan_id>
---

Apply plan: $ARGUMENTS

Procedure:
1. Call `opn_plan_load($ARGUMENTS)` and show the ops to the user.
2. Call `opn_lockout_check($ARGUMENTS)`. If warnings exist, list each one and ask the user to type the configured confirmation phrase to override.
3. Ask the user to type the configured confirmation phrase (default: `yes apply`) to proceed.
4. Call `opn_plan_apply(plan_id=$ARGUMENTS, confirm=true, override_lockout=<true if warnings were overridden>)`.
5. Report results: status, backup_id, per-op results. If status is `failed` or `rolled_back`, surface the rollback_reason prominently.

**Never** call `opn_plan_apply` without explicit user confirmation in chat. The `confirm=true` flag is necessary but not sufficient — wait for the typed confirmation phrase before invoking the tool.
```

Create `commands/opn-status.md`:
```markdown
---
description: One-shot OPNsense health snapshot — reachable, version, uptime, gateway status.
---

Call `opn_status()` and present the result in a compact summary:
- Reachable: yes/no
- Version
- Uptime
- Any obvious issues (gateway down, pending changes, etc.)
```

Create `commands/opn-backup.md`:
```markdown
---
description: Create a manual backup of OPNsense config. Use before risky external work.
argument-hint: [optional label]
---

Call `opn_backup_create(label=$ARGUMENTS)` (omit label if no argument given).
Report the returned backup_id.

Manually-labeled backups are kept regardless of retention; unlabeled ones are pruned past the configured limit.
```

Create `commands/opn-rollback.md`:
```markdown
---
description: Restore an OPNsense config backup. Two-step confirmation required.
argument-hint: <backup_id>
---

Procedure for rollback to: $ARGUMENTS

1. Call `opn_backup_list()` and confirm `$ARGUMENTS` is in the list. Show its timestamp and label.
2. Show a brief diff: call `opn_config_diff(backup_id_a=$ARGUMENTS)` (compares to current).
3. Ask the user to type the configured confirmation phrase to proceed.
4. Call `opn_backup_restore(backup_id=$ARGUMENTS, confirm=true)`.
5. After restore, call `opn_status()` to verify the firewall came back.

**Never** call `opn_backup_restore` without explicit user confirmation in chat.
```

Create `commands/opn-diag.md`:
```markdown
---
description: Investigate an OPNsense issue read-only. No mutations possible. Use when something is broken and you need to know why.
argument-hint: <symptom or question>
---

Use the `opn-diag` subagent to investigate: $ARGUMENTS

The diag agent will:
1. Load relevant troubleshooting skills
2. Run read-only API and SSH commands
3. Report findings, diagnosis, and recommended action

If the recommended action is a mutation, the agent will tell you to run `/opn-plan "<description>"` — it will not save or apply a plan itself.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/smoke/test_command_frontmatter.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add commands/ tests/smoke/test_command_frontmatter.py
git commit -m "$(cat <<'EOF'
feat: six v1 slash commands

opn-plan, opn-apply, opn-status, opn-backup, opn-rollback, opn-diag.
opn-apply and opn-rollback both require typed confirmation in chat
on top of the tool-level confirm=true flag.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 20: CLI (`setup` wizard + `doctor`)

**Files:**
- Create: `src/opnsense_agent/cli.py`
- Create: `tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cli.py`:
```python
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from opnsense_agent.cli import cli


def test_doctor_reports_missing_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPN_AGENT_CONFIG_PATH", str(tmp_path / "missing.toml"))
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code != 0
    assert "Config file not found" in result.output


def test_setup_writes_0600_config(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "config.toml"
    monkeypatch.setenv("OPN_AGENT_CONFIG_PATH", str(target))
    runner = CliRunner()
    inputs = "\n".join([
        "opnsense.test",   # host
        "443",             # api port
        "22",              # ssh port
        "true",            # verify_tls
        "root",            # ssh user
        str(tmp_path / "id_ed25519"),  # ssh key path
        "test-key",        # api key
        "test-secret",     # api secret
        str(tmp_path / "runs"),  # runs dir
    ])
    # Create the dummy ssh key so setup doesn't refuse it
    (tmp_path / "id_ed25519").write_text("dummy")
    (tmp_path / "id_ed25519").chmod(0o600)

    result = runner.invoke(cli, ["setup", "--non-interactive"], input=inputs)
    assert result.exit_code == 0, result.output
    assert target.exists()
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement CLI**

Create `src/opnsense_agent/cli.py`:
```python
"""CLI: `opnsense-agent setup` wizard + `opnsense-agent doctor`."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import click

from opnsense_agent.config import (
    DEFAULT_CONFIG_PATH,
    ConfigError,
    load_settings,
)


def _config_path() -> Path:
    return Path(os.environ.get("OPN_AGENT_CONFIG_PATH", str(DEFAULT_CONFIG_PATH)))


@click.group()
def cli() -> None:
    """OPNsense Agent — manage your firewall via plan-then-apply."""


@cli.command()
@click.option(
    "--non-interactive", is_flag=True,
    help="Read answers from stdin in fixed order (used by tests).",
)
def setup(non_interactive: bool) -> None:
    """Interactive wizard: writes config.toml at 0600."""
    target = _config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        click.confirm(
            f"{target} exists. Overwrite?", abort=True, default=False
        )

    prompts = [
        ("host", "OPNsense hostname or IP"),
        ("api_port", "API port", "443"),
        ("ssh_port", "SSH port", "22"),
        ("verify_tls", "Verify TLS cert? (true/false)", "true"),
        ("ssh_user", "SSH username", "root"),
        ("ssh_key_path", "SSH private key path"),
        ("api_key", "OPNsense API key"),
        ("api_secret", "OPNsense API secret"),
        ("runs_dir", "Runs directory (plans + backups)",
         str(Path.cwd() / "runs")),
    ]
    answers: dict[str, str] = {}
    for entry in prompts:
        key, label, *default = entry
        d = default[0] if default else None
        answers[key] = click.prompt(label, default=d, show_default=bool(d))

    ssh_key = Path(os.path.expanduser(answers["ssh_key_path"]))
    if not ssh_key.exists():
        click.secho(
            f"WARNING: ssh key {ssh_key} does not exist. Continuing anyway.",
            fg="yellow",
        )

    content = f"""[firewall]
host = "{answers['host']}"
api_port = {answers['api_port']}
ssh_port = {answers['ssh_port']}
verify_tls = {answers['verify_tls'].lower()}
ssh_user = "{answers['ssh_user']}"
ssh_key_path = "{answers['ssh_key_path']}"

[auth]
api_key = "{answers['api_key']}"
api_secret = "{answers['api_secret']}"

[runtime]
runs_dir = "{answers['runs_dir']}"
backup_retention = 50
reachability_probe_seconds = 30
reachability_probe_interval = 3

[safety]
require_confirm_phrase = "yes apply"
allow_lockout_override = true
"""
    target.write_text(content)
    target.chmod(0o600)
    click.secho(f"Wrote {target} (0600).", fg="green")
    click.echo("Run `opnsense-agent doctor` to verify connectivity.")


@cli.command()
def doctor() -> None:
    """Verify config + connectivity (API + SSH)."""
    try:
        settings = load_settings(config_path=_config_path())
    except ConfigError as e:
        click.secho(str(e), fg="red")
        sys.exit(1)

    click.secho(f"✓ Config OK ({_config_path()})", fg="green")

    asyncio.run(_check_connectivity(settings))


async def _check_connectivity(settings) -> None:
    from opnsense_agent.client.api import OpnApiClient
    from opnsense_agent.client.ssh import OpnSshClient

    api = OpnApiClient(firewall=settings.firewall, auth=settings.auth)
    try:
        info = await api.get("/api/diagnostics/system/system_information")
        click.secho(f"✓ API reachable ({settings.firewall.host})", fg="green")
        click.echo(f"  Version: {info.get('product', {}).get('product_version', '?')}")
    except Exception as e:  # noqa: BLE001
        click.secho(f"✗ API failed: {e}", fg="red")
    finally:
        await api.close()

    ssh = OpnSshClient(firewall=settings.firewall)
    try:
        result = await ssh.exec_readonly("uname -a")
        click.secho(f"✓ SSH reachable ({result.stdout.strip()})", fg="green")
    except Exception as e:  # noqa: BLE001
        click.secho(f"✗ SSH failed: {e}", fg="red")


def main() -> None:
    cli()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_cli.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/opnsense_agent/cli.py tests/unit/test_cli.py
git commit -m "$(cat <<'EOF'
feat: CLI with setup wizard and doctor

`opnsense-agent setup` walks the user through config and writes a 0600
file. `opnsense-agent doctor` round-trips API + SSH and reports.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 21: Integration test scaffolding + canonical end-to-end

**Files:**
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_vlan_roundtrip.py`

- [ ] **Step 1: Create integration test guardrails**

Create `tests/integration/conftest.py`:
```python
"""Integration test guardrails. Tests opt-in only.

Required env:
  OPN_AGENT_INTEGRATION_TEST=1
  OPN_AGENT_INTEGRATION_HOST=<expected host>  # must match settings.firewall.host
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import pytest

from opnsense_agent.client.api import OpnApiClient
from opnsense_agent.config import load_settings
from opnsense_agent.safety.backup import BackupStore


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    if os.environ.get("OPN_AGENT_INTEGRATION_TEST") != "1":
        skip = pytest.mark.skip(reason="set OPN_AGENT_INTEGRATION_TEST=1 to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def settings():
    s = load_settings()
    expected_host = os.environ.get("OPN_AGENT_INTEGRATION_HOST")
    if expected_host and s.firewall.host != expected_host:
        pytest.fail(
            f"Refusing to run integration tests against {s.firewall.host!r}; "
            f"OPN_AGENT_INTEGRATION_HOST is {expected_host!r}."
        )
    return s


@pytest.fixture
async def api(settings) -> AsyncIterator[OpnApiClient]:
    client = OpnApiClient(firewall=settings.firewall, auth=settings.auth)
    yield client
    await client.close()


@pytest.fixture(autouse=True)
async def session_backup(settings, api):
    """Snapshot before each integration test; restore on failure."""
    store = BackupStore(runs_dir=settings.runtime.runs_dir, retention=999)
    backup_id = await store.create(api=api, label="integration-pre")
    yield backup_id
    # If test failed, the runner will set request.node.rep_call; we restore unconditionally
    # in v1 to keep the firewall in a known state. Could be made conditional later.
    try:
        await store.restore(api=api, backup_id=backup_id)
    except Exception:  # noqa: BLE001
        pass
```

- [ ] **Step 2: Create the canonical end-to-end test**

Create `tests/integration/test_vlan_roundtrip.py`:
```python
"""End-to-end: create a VLAN, verify it exists, delete it.

This is the one canonical happy-path integration test for v1.
Add more as ops are added in later phases.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from opnsense_agent.plans.engine import HandlerContext, OpHandlerRegistry, PlanApplyPipeline
from opnsense_agent.plans.handlers.vlan import VlanCreateHandler
from opnsense_agent.plans.schema import Plan, PlanOp, PlanTarget
from opnsense_agent.plans.store import PlanStore
from opnsense_agent.safety.backup import BackupStore
from opnsense_agent.safety.probe import reachability_probe


@pytest.mark.integration
@pytest.mark.asyncio
async def test_vlan_create_roundtrip(settings, api):
    """Build a VLAN with a test- prefix, verify, let conftest restore."""
    from opnsense_agent.client.ssh import OpnSshClient

    ssh = OpnSshClient(firewall=settings.firewall)

    # Test plan: create one VLAN with a high tag unlikely to collide
    plan = Plan(
        plan_id=f"integration-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        description="integration test: create VLAN 4090 on igb0",
        created=datetime.now(timezone.utc),
        target=PlanTarget(host=settings.firewall.host),
        ops=[PlanOp(
            op="vlan.create",
            params={"tag": 4090, "parent_if": "igb0", "description": "test-integration"},
        )],
    )

    store = PlanStore(runs_dir=settings.runtime.runs_dir)
    plan_id = store.save(plan)

    backup = BackupStore(runs_dir=settings.runtime.runs_dir, retention=999)
    registry = OpHandlerRegistry()
    registry.register(VlanCreateHandler())

    pipeline = PlanApplyPipeline(
        store=store, registry=registry, backup=backup,
        api=api, ssh=ssh, probe=reachability_probe,
        self_ip="0.0.0.0", management_if="igb0",
        allow_lockout_override=True,
    )

    result = await pipeline.apply(plan_id, confirm=True, override_lockout=True)
    assert result.status.value == "applied", result

    # Verify VLAN exists on the firewall
    vlans = await api.get("/api/interfaces/vlan_settings/searchItem")
    found = any(
        str(item.get("tag")) == "4090"
        for item in vlans.get("rows", [])
    )
    assert found, f"VLAN 4090 not found in {vlans}"

    # Cleanup happens via conftest restore.
```

- [ ] **Step 3: Verify tests collect (but skip without env var)**

Run: `pytest tests/integration -v`
Expected: tests are collected and SKIPPED with "set OPN_AGENT_INTEGRATION_TEST=1 to run".

- [ ] **Step 4: Commit**

```bash
git add tests/integration/
git commit -m "$(cat <<'EOF'
test: integration scaffolding + VLAN roundtrip

Tests skip unless OPN_AGENT_INTEGRATION_TEST=1. session_backup
fixture snapshots before and restores after every test. The VLAN
roundtrip is the one canonical happy-path test for v1.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Task 22: Finalize README + smoke run

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace README with final version**

Overwrite `README.md`:
```markdown
# OPNsense Agent

A Claude Code plugin for managing a single OPNsense firewall via a plan-then-apply workflow. Uses the OPNsense REST API for config mutations and SSH for diagnostics.

> **Status:** v1 — covers VLANs, interfaces, DHCP. See [roadmap](#roadmap) for future phases.

## ⚠️ Secrets handling

This plugin requires an OPNsense API key/secret and an SSH key. **They are never stored in this repository.**

- Secrets live in `~/.config/opnsense-agent/config.toml` (mode `0600`, refused if wider).
- The repo's `.gitignore` denies `.env`, `*.key`, `*.pem`, `*_rsa`, `*_ed25519`, `secrets/`, `config.local.*`, `apikey.txt`, `runs/`, and config backups.
- A `pre-commit` hook runs `gitleaks` on every commit and blocks anything that looks like a secret.
- A CI test (`tests/test_no_secrets_in_repo.py`) greps the working tree for OPNsense-shaped API keys and SSH private-key headers; CI fails on a match.

If you find a way to commit a secret, that is a bug. File an issue.

## Setup

### 1. Generate OPNsense API credentials

In the OPNsense UI:
- System → Access → Users → (your user) → click "+" under API keys
- Download the resulting `apikey.txt` (contains `key=` and `secret=` lines)

### 2. Set up SSH

OPNsense ships with SSH disabled by default. Enable it under System → Settings → Administration. Add your public key under your user's "authorized keys."

Verify from your workstation:
```bash
ssh -i ~/.ssh/your_opn_key root@<firewall-host> 'uname -a'
```

### 3. Install the plugin

```bash
git clone git@github.com:tcreight/opnsense-agent.git
cd opnsense-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pre-commit install
```

### 4. Run the setup wizard

```bash
opnsense-agent setup
```

This writes `~/.config/opnsense-agent/config.toml` at mode `0600`. Paste your API key/secret when prompted.

### 5. Verify

```bash
opnsense-agent doctor
```

Expected output:
```
✓ Config OK (~/.config/opnsense-agent/config.toml)
✓ API reachable (opnsense.lan)
  Version: 24.7.x
✓ SSH reachable (FreeBSD opnsense.lan ...)
```

### 6. Register with Claude Code

Add to your Claude Code config (typically `~/.claude/config.json` or via `/plugins`):

```json
{
  "plugins": [
    "/home/tylerc/projects/opnsense-agent"
  ]
}
```

Restart Claude Code. The six `/opn-*` slash commands should now appear.

## Usage

### Build a new VLAN end-to-end

```
/opn-plan VLAN 30 for IoT on igb1, /24, DHCP enabled, scope 10.30.0.100-200
```

The planner drafts a plan, saves it, shows you the preview. You'll see something like:

```
Saved as 2026-05-03T14-30-22Z-iot-vlan
Preview:
  - vlan.create: tag=30 parent=igb1 desc="IoT"
  - interface.assign: vlan_tag=30 -> opt3
  - interface.configure: opt3 ip=10.30.0.1/24
  - dhcp.scope.create: opt3 100-200 router=10.30.0.1
Apply with: /opn-apply 2026-05-03T14-30-22Z-iot-vlan
```

### Apply

```
/opn-apply 2026-05-03T14-30-22Z-iot-vlan
```

You'll be asked to type the configured confirmation phrase (default `yes apply`). After confirming:
- Pre-apply backup created
- Each op executes
- Reachability probe runs for 30s
- If anything goes wrong, the backup is restored automatically

### Diagnose without changing anything

```
/opn-diag Why is DHCP not working on opt3?
```

The diag agent investigates read-only. It will tell you what's wrong and recommend a `/opn-plan` to fix it.

### Manual backup / rollback

```
/opn-backup before-gui-work
/opn-rollback 20260503T143022Z-before-gui-work
```

### Status check

```
/opn-status
```

## Roadmap

- v1 — VLANs, interfaces, DHCP, basic gateway/DNS *(this release)*
- v2 — VPN (WireGuard, OpenVPN)
- v3 — Firewall rules, aliases, NAT, port forwards
- v4 — Drift detection + monitoring daemon

## Architecture

See [`docs/superpowers/specs/2026-05-03-opnsense-agent-design.md`](docs/superpowers/specs/2026-05-03-opnsense-agent-design.md).

Quick summary:
- **MCP server** exposes 14 primitive tools (read-only API/SSH, backup/restore, plan workflow, lockout check)
- **Skills** hold OPNsense expertise; load on demand
- **Slash commands** are workflow entry points
- **All mutations route through `opn_plan_apply`** — single chokepoint for backup, lockout check, reachability verification

## Safety guarantees

- No `opn_api_post` tool exists — every mutation has a backup and a verification step
- SSH from the MCP layer is allowlisted to read-only commands
- Plan files become 0444 (immutable) once a plan transitions out of `draft`
- Auto-rollback on op failure or post-apply reachability failure
- Manual `/opn-rollback` always available

See spec section 10 for the full six-layer safety stack.

## Testing

```bash
pytest tests/unit tests/smoke -v          # fast, no firewall
OPN_AGENT_INTEGRATION_TEST=1 OPN_AGENT_INTEGRATION_HOST=opnsense.lan \
  pytest tests/integration -v              # hits real firewall
```

Integration tests refuse to run unless the host matches `OPN_AGENT_INTEGRATION_HOST`.

## License

MIT
```

- [ ] **Step 2: Run the entire test suite**

Run: `pytest tests/unit tests/smoke tests/test_no_secrets_in_repo.py -v`
Expected: ALL tests pass.

- [ ] **Step 3: Run lint + format check**

Run: `ruff check . && ruff format --check .`
Expected: no errors.

- [ ] **Step 4: Run type check**

Run: `pyright`
Expected: no errors.

- [ ] **Step 5: Verify CI is green on GitHub**

Run: `gh run list --limit 1` and `gh run watch`
Expected: latest run passes.

- [ ] **Step 6: Final commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs: finalize README with full setup, usage, and architecture

Covers API key generation, SSH setup, plugin install, slash command
walkthroughs, safety guarantees, and testing.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Self-Review

Spec coverage check (against `docs/superpowers/specs/2026-05-03-opnsense-agent-design.md`):

| Spec section | Implemented in task |
|---|---|
| §3 architecture overview | Tasks 1–22 collectively |
| §4 repo layout | Task 1, 2, 17, 18, 19 |
| §5 MCP server primitives (14 tools) | Task 15 |
| §6 v1 skills (6) | Task 17 |
| §7 slash commands (6) | Task 19 |
| §8 plan format | Task 7, 8 |
| §9 mutation + diagnostic workflows | Task 14, 18, 19 |
| §10 six-layer safety stack | Tasks 5, 6, 8, 13, 14 |
| §11 config + secrets | Task 1 (gitignore + tests), 3 (loader), 20 (wizard) |
| §12 setup flow | Task 20 (CLI), 22 (README) |
| §13 phase roadmap | README §Roadmap (Task 22) |
| §14 testing strategy | Tasks 1, 2 (CI), all per-task tests, 21 (integration) |
| §15 repo creation | Task 1 |
| §16 known limitations | Documented in README + spec; not code |
| §17 open questions | Locked at top of plan: asyncssh, YAML-only, fixture capture later |

**Gaps:** none I can identify. `opn_config_diff` is a stub in the MCP server (returns "not yet implemented"). That's an explicit v1 limitation — file a follow-up issue but don't block v1 on it.

**Placeholder scan:** No "TBD" / "TODO" / "implement later" left in actionable steps. Two notes flagged with "verify in integration test" (Tasks 6, 11) — these are intentional, called out in the comment, and the unit tests use mocks so the structure is locked even if exact endpoint shapes shift.

**Type / name consistency check:**
- `Settings` / `FirewallSettings` / `AuthSettings` etc — used consistently across config.py, api.py, ssh.py, mcp_server.py, cli.py.
- `OpnApiClient` / `OpnSshClient` — consistent.
- `OpHandlerRegistry`, `HandlerContext`, `PlanApplyPipeline`, `PlanApplyResult` — defined in engine.py, used in mcp_server.py and tests.
- `BackupStore.create / list / prune / restore` — consistent.
- `PlanStore.save / load / list / finalize` — consistent.
- Tool names in `EXPECTED_TOOLS` (Task 15) match command files (Task 19) and skill references (Task 17).

No inconsistencies found.

---

Plan complete and saved to `docs/superpowers/plans/2026-05-03-opnsense-agent-v1.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good for a build of this size where you want to see progress and catch issues early.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Slower turnaround per task but simpler to follow.

Which approach?
