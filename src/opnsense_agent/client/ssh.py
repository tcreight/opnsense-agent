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
            known_hosts=None,  # homelab; TOFU tradeoff documented in README
        ) as conn:
            result = await conn.run(command, check=False, timeout=timeout)
        return SshResult(
            stdout=str(result.stdout or ""),
            stderr=str(result.stderr or ""),
            exit_code=int(result.exit_status or 0),
        )
