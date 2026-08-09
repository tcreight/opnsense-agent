"""Smoke test: MCP server registers the expected tool names.

The low-level ``mcp.server.Server`` exposes ``list_tools`` as a *decorator*,
not an accessor — so we introspect the registered tools by invoking the
handler the decorator stored (see ``list_registered_tools``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opnsense_agent.config import (
    AuthSettings,
    FirewallSettings,
    RuntimeSettings,
    SafetySettings,
    Settings,
)
from opnsense_agent.mcp_server import (
    EXPECTED_TOOLS,
    build_server,
    list_registered_tools,
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A fully-populated Settings that touches no real firewall or config file."""
    key = tmp_path / "id_ed25519"
    key.write_text("fake-key")
    return Settings(
        firewall=FirewallSettings(
            host="192.0.2.1",
            api_port=443,
            ssh_port=22,
            verify_tls=False,
            ssh_user="root",
            ssh_key_path=key,
        ),
        auth=AuthSettings(api_key="k", api_secret="s"),
        runtime=RuntimeSettings(
            runs_dir=tmp_path / "runs",
            backup_retention=50,
            reachability_probe_seconds=30,
            reachability_probe_interval=3,
        ),
        safety=SafetySettings(
            require_confirm_phrase="APPLY",
            allow_lockout_override=False,
        ),
    )


def test_server_registers_all_expected_tools(settings: Settings) -> None:
    server = build_server(settings=settings)
    registered = {t.name for t in list_registered_tools(server)}
    assert registered == set(EXPECTED_TOOLS), (
        f"Missing: {set(EXPECTED_TOOLS) - registered}; "
        f"Unexpected: {registered - set(EXPECTED_TOOLS)}"
    )


def test_no_opn_api_post_tool_exists(settings: Settings) -> None:
    """Critical invariant from the spec: there is no opn_api_post tool.

    All mutation must funnel through opn_plan_apply -> PlanApplyPipeline.
    """
    server = build_server(settings=settings)
    names = {t.name for t in list_registered_tools(server)}
    assert "opn_api_post" not in names


async def test_dispatch_config_diff_vs_current(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from opnsense_agent.mcp_server import _dispatch  # pyright: ignore[reportPrivateUsage]
    from opnsense_agent.safety.backup import BackupStore

    store = BackupStore(runs_dir=tmp_path, retention=10)
    api = AsyncMock()
    # Backup snapshot: sysctl value 0.
    api.get.return_value = "<opnsense><sysctl><item><value>0</value></item></sysctl></opnsense>"
    backup_id = await store.create(api=api)
    # Live config now: sysctl value 1.
    api.get.return_value = "<opnsense><sysctl><item><value>1</value></item></sysctl></opnsense>"

    out = await _dispatch(
        "opn_config_diff",
        {"backup_id_a": backup_id},
        api=api,
        ssh=MagicMock(),
        backup=store,
        plan_store=MagicMock(),
        pipeline=MagicMock(),
        self_ip="0.0.0.0",
        management_if="igb0",
    )

    # baseline=current (value 1) -> target=backup (value 0): restoring reverts 1 -> 0.
    assert out.splitlines()[0].startswith("Changes from current to backup ")
    assert "sysctl/item/value: 1 -> 0" in out


async def test_dispatch_config_diff_backup_vs_backup(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from opnsense_agent.mcp_server import _dispatch  # pyright: ignore[reportPrivateUsage]
    from opnsense_agent.safety.backup import BackupStore

    store = BackupStore(runs_dir=tmp_path, retention=10)
    api = AsyncMock()
    # baseline backup (backup_id_b): sysctl value 0.
    api.get.return_value = "<opnsense><sysctl><item><value>0</value></item></sysctl></opnsense>"
    baseline_id = await store.create(api=api)
    # target backup (backup_id_a): sysctl value 1.
    api.get.return_value = "<opnsense><sysctl><item><value>1</value></item></sysctl></opnsense>"
    target_id = await store.create(api=api)

    out = await _dispatch(
        "opn_config_diff",
        {"backup_id_a": target_id, "backup_id_b": baseline_id},
        api=api,
        ssh=MagicMock(),
        backup=store,
        plan_store=MagicMock(),
        pipeline=MagicMock(),
        self_ip="0.0.0.0",
        management_if="igb0",
    )

    # baseline=backup_id_b (value 0) -> target=backup_id_a (value 1).
    assert out.splitlines()[0] == f"Changes from backup {baseline_id} to backup {target_id}:"
    assert "sysctl/item/value: 0 -> 1" in out


async def test_dispatch_config_diff_redacts_secret_values(tmp_path: Path) -> None:
    """End-to-end: a changed PSK never appears in the tool's output text."""
    from unittest.mock import AsyncMock, MagicMock

    from opnsense_agent.mcp_server import _dispatch  # pyright: ignore[reportPrivateUsage]
    from opnsense_agent.safety.backup import BackupStore

    store = BackupStore(runs_dir=tmp_path, retention=10)
    api = AsyncMock()
    old_psk = "old-wireguard-psk-material"
    new_psk = "new-wireguard-psk-material"
    api.get.return_value = (
        f"<opnsense><ipsec><presharedkey>{old_psk}</presharedkey></ipsec></opnsense>"
    )
    backup_id = await store.create(api=api)
    api.get.return_value = (
        f"<opnsense><ipsec><presharedkey>{new_psk}</presharedkey></ipsec></opnsense>"
    )

    out = await _dispatch(
        "opn_config_diff",
        {"backup_id_a": backup_id},
        api=api,
        ssh=MagicMock(),
        backup=store,
        plan_store=MagicMock(),
        pipeline=MagicMock(),
        self_ip="0.0.0.0",
        management_if="igb0",
    )

    assert isinstance(out, str)
    assert old_psk not in out
    assert new_psk not in out
    # The path still shows as changed — only the values are hidden.
    assert "ipsec/presharedkey: [redacted] -> [redacted]" in out


async def test_dispatch_backup_restore_rejected_while_apply_in_flight(tmp_path: Path) -> None:
    """A manual restore is a mutation: while the pipeline's mutation lock is
    held (an apply in flight), opn_backup_restore must refuse, not queue."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from opnsense_agent.mcp_server import _dispatch  # pyright: ignore[reportPrivateUsage]
    from opnsense_agent.safety.backup import BackupStore

    store = BackupStore(runs_dir=tmp_path, retention=10)
    api = AsyncMock()
    api.get.return_value = "<opnsense><x/></opnsense>"
    backup_id = await store.create(api=api)

    pipeline = MagicMock()
    pipeline.mutation_lock = asyncio.Lock()

    async with pipeline.mutation_lock:
        out = await _dispatch(
            "opn_backup_restore",
            {"backup_id": backup_id, "confirm": True},
            api=api,
            ssh=MagicMock(),
            backup=store,
            plan_store=MagicMock(),
            pipeline=pipeline,
            self_ip="0.0.0.0",
            management_if="igb0",
        )
    assert out == "REJECTED: an apply or restore is already in progress; retry when it completes."
    api.post.assert_not_awaited()

    # Lock released: the same restore now goes through.
    out = await _dispatch(
        "opn_backup_restore",
        {"backup_id": backup_id, "confirm": True},
        api=api,
        ssh=MagicMock(),
        backup=store,
        plan_store=MagicMock(),
        pipeline=pipeline,
        self_ip="0.0.0.0",
        management_if="igb0",
    )
    assert out == {"status": "restored", "backup_id": backup_id}
    api.post.assert_awaited_once()
