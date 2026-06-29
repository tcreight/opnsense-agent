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
    Settings,
    load_settings,
)


def _config_path() -> Path:
    return Path(os.environ.get("OPN_AGENT_CONFIG_PATH", str(DEFAULT_CONFIG_PATH)))


@click.group()
def cli() -> None:
    """OPNsense Agent — manage your firewall via plan-then-apply."""


@cli.command()
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Read answers from stdin in fixed order (used by tests).",
)
def setup(non_interactive: bool) -> None:  # noqa: ARG001  (flag is a CLI contract marker)
    """Interactive wizard: writes config.toml at 0600."""
    target = _config_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        click.confirm(f"{target} exists. Overwrite?", abort=True, default=False)

    prompts: list[tuple[str, str, str | None]] = [
        ("host", "OPNsense hostname or IP", None),
        ("api_port", "API port", "443"),
        ("ssh_port", "SSH port", "22"),
        ("verify_tls", "Verify TLS cert? (true/false)", "true"),
        ("ssh_user", "SSH username", "root"),
        ("ssh_key_path", "SSH private key path", None),
        ("api_key", "OPNsense API key", None),
        ("api_secret", "OPNsense API secret", None),
        ("runs_dir", "Runs directory (plans + backups)", str(Path.cwd() / "runs")),
    ]
    answers: dict[str, str] = {}
    for key, label, default in prompts:
        answers[key] = click.prompt(label, default=default, show_default=bool(default))

    ssh_key = Path(answers["ssh_key_path"]).expanduser()
    if not ssh_key.exists():
        click.secho(
            f"WARNING: ssh key {ssh_key} does not exist. Continuing anyway.",
            fg="yellow",
        )

    content = f"""[firewall]
host = "{answers["host"]}"
api_port = {answers["api_port"]}
ssh_port = {answers["ssh_port"]}
verify_tls = {answers["verify_tls"].lower()}
ssh_user = "{answers["ssh_user"]}"
ssh_key_path = "{answers["ssh_key_path"]}"

[auth]
api_key = "{answers["api_key"]}"
api_secret = "{answers["api_secret"]}"

[runtime]
runs_dir = "{answers["runs_dir"]}"
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


async def _check_connectivity(settings: Settings) -> None:
    from opnsense_agent.client.api import OpnApiClient
    from opnsense_agent.client.ssh import OpnSshClient

    api = OpnApiClient(firewall=settings.firewall, auth=settings.auth)
    try:
        info = await api.get("/api/diagnostics/system/system_information")
        click.secho(f"✓ API reachable ({settings.firewall.host})", fg="green")
        product = info.get("product", {})
        click.echo(f"  Version: {product.get('product_version', '?')}")
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
