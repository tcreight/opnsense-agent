"""End-to-end: create a VLAN, verify it exists, let conftest restore.

This is the one canonical happy-path integration test for v1.
Add more as ops are added in later phases.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from opnsense_agent.client.api import OpnApiClient
from opnsense_agent.client.ssh import OpnSshClient
from opnsense_agent.config import Settings
from opnsense_agent.plans.engine import OpHandlerRegistry, PlanApplyPipeline
from opnsense_agent.plans.handlers.vlan import VlanCreateHandler
from opnsense_agent.plans.schema import Plan, PlanOp, PlanStatus, PlanTarget
from opnsense_agent.plans.store import PlanStore
from opnsense_agent.safety.backup import BackupStore
from opnsense_agent.safety.probe import reachability_probe


@pytest.mark.integration
async def test_vlan_create_roundtrip(settings: Settings, api: OpnApiClient) -> None:
    """Build a VLAN with a test- prefix, verify it lands, let conftest restore."""
    ssh = OpnSshClient(firewall=settings.firewall)

    now = datetime.now(UTC)
    # High tag (4090) unlikely to collide with anything real on the firewall.
    plan = Plan(
        plan_id=f"integration-{now.strftime('%Y%m%dT%H%M%SZ')}",
        description="integration test: create VLAN 4090 on igb0",
        created=now,
        target=PlanTarget(host=settings.firewall.host),
        ops=[
            PlanOp(
                op="vlan.create",
                params={"tag": 4090, "parent_if": "igb0", "description": "test-integration"},
            )
        ],
    )

    store = PlanStore(runs_dir=settings.runtime.runs_dir)
    plan_id = store.save(plan)

    backup = BackupStore(runs_dir=settings.runtime.runs_dir, retention=999)
    registry = OpHandlerRegistry()
    registry.register(VlanCreateHandler())

    pipeline = PlanApplyPipeline(
        store=store,
        registry=registry,
        backup=backup,
        api=api,
        ssh=ssh,
        probe=reachability_probe,
        self_ip="0.0.0.0",
        management_if="igb0",
        allow_lockout_override=True,
    )

    result = await pipeline.apply(plan_id, confirm=True, override_lockout=True)
    assert result.status is PlanStatus.applied, result

    # Verify the VLAN actually exists on the firewall.
    vlans = await api.get("/api/interfaces/vlan_settings/searchItem")
    found = any(str(item.get("tag")) == "4090" for item in vlans.get("rows", []))
    assert found, f"VLAN 4090 not found in {vlans}"

    # Cleanup happens via the autouse session_backup fixture restore.
