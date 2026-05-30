from __future__ import annotations

from pathlib import Path

import pytest

from opnsense_agent.client.ssh import is_command_allowed
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
