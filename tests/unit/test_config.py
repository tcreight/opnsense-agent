from __future__ import annotations

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


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o660])
def test_refuses_insecure_config_permissions(tmp_path: Path, mode: int) -> None:
    cfg = _write_config(tmp_path, VALID_TOML, mode=mode)
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
