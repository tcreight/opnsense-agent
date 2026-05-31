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


def test_warns_on_management_interface_ip_change() -> None:
    """Changing the IP of the mgmt interface will sever the agent's API
    connection mid-apply; flag it explicitly."""
    plan = _plan(
        [
            PlanOp(
                op="interface.configure",
                params={"opn_if_name": "igb0", "ipv4": "10.0.0.99", "ipv4_subnet": 24},
            )
        ]
    )
    warnings = check_plan(plan, self_ip="10.0.0.50", management_if="igb0")
    assert any("changes the ip" in w.message.lower() for w in warnings)


def test_warns_on_rule_delete() -> None:
    """rule.delete cannot be inspected statically without an API fetch,
    so the lockout check warns conservatively on every rule deletion."""
    plan = _plan([PlanOp(op="rule.delete", params={"rule_uuid": "abc-123"})])
    warnings = check_plan(plan, self_ip="10.0.0.50", management_if="igb0")
    assert len(warnings) == 1
    assert "rule deletion" in warnings[0].message.lower()
    assert "10.0.0.50" in warnings[0].message  # self_ip surfaced for the operator


def test_no_warning_for_non_dangerous_service_disable() -> None:
    """Disabling a non-management service (e.g. ntp) must NOT trigger a
    lockout warning — only the curated allowlist of management services does."""
    plan = _plan([PlanOp(op="service.disable", params={"name": "ntpd"})])
    warnings = check_plan(plan, self_ip="10.0.0.50", management_if="igb0")
    assert warnings == []


def test_no_warning_for_non_management_interface_disable() -> None:
    """Disabling a non-mgmt interface is fine — only the mgmt interface
    must be protected."""
    plan = _plan(
        [
            PlanOp(
                op="interface.configure",
                params={"opn_if_name": "opt3", "enabled": False},
            )
        ]
    )
    warnings = check_plan(plan, self_ip="10.0.0.50", management_if="igb0")
    assert warnings == []
