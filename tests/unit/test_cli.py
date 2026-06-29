from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from opnsense_agent.cli import cli


def test_doctor_reports_missing_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPN_AGENT_CONFIG_PATH", str(tmp_path / "missing.toml"))
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code != 0
    assert "Config file not found" in result.output


def test_setup_writes_0600_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "config.toml"
    monkeypatch.setenv("OPN_AGENT_CONFIG_PATH", str(target))
    runner = CliRunner()
    inputs = "\n".join(
        [
            "opnsense.test",  # host
            "443",  # api port
            "22",  # ssh port
            "true",  # verify_tls
            "root",  # ssh user
            str(tmp_path / "id_ed25519"),  # ssh key path
            "test-key",  # api key
            "test-secret",  # api secret
            str(tmp_path / "runs"),  # runs dir
        ]
    )
    # Create the dummy ssh key so setup doesn't refuse it
    (tmp_path / "id_ed25519").write_text("dummy")
    (tmp_path / "id_ed25519").chmod(0o600)

    result = runner.invoke(cli, ["setup", "--non-interactive"], input=inputs)
    assert result.exit_code == 0, result.output
    assert target.exists()
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600
