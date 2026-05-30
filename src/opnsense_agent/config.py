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
    data = {section: dict(vals) for section, vals in data.items()}
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
            f"Config file not found at {path}. Run `opnsense-agent setup` to create one."
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
            require_confirm_phrase=data["safety"].get("require_confirm_phrase", "yes apply"),
            allow_lockout_override=_coerce_bool(
                data["safety"].get("allow_lockout_override", False)
            ),
        )
    except KeyError as e:
        raise ConfigError(f"Missing required config key: {e}") from e

    return Settings(firewall=firewall, auth=auth, runtime=runtime, safety=safety)
