from __future__ import annotations

from opnsense_agent.plans.schema import Plan, PlanOp, PlanTarget
from opnsense_agent.safety.lockout import check_plan


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
    plan = _plan(
        [
            PlanOp(
                op="interface.configure",
                params={"opn_if_name": "igb0", "enabled": False},
            )
        ]
    )
    warnings = check_plan(plan, self_ip="10.0.0.50", management_if="igb0")
    assert any("management interface" in w.message.lower() for w in warnings)


def test_warns_on_ssh_service_disable() -> None:
    plan = _plan([PlanOp(op="service.disable", params={"name": "openssh"})])
    warnings = check_plan(plan, self_ip="10.0.0.50", management_if="igb0")
    assert any("ssh" in w.message.lower() for w in warnings)
