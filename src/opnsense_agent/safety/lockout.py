"""Pre-apply lockout check: refuses risky plan ops or surfaces warnings."""

from __future__ import annotations

from dataclasses import dataclass

from opnsense_agent.plans.schema import Plan, PlanOp


@dataclass(frozen=True)
class LockoutWarning:
    op_index: int
    op_type: str
    message: str


_DANGEROUS_SERVICES = {"openssh", "sshd", "nginx", "lighttpd", "configd"}


def _check_op(op: PlanOp, idx: int, *, self_ip: str, management_if: str) -> list[LockoutWarning]:
    warnings: list[LockoutWarning] = []
    p = op.params

    if op.op == "interface.configure":
        if p.get("opn_if_name") == management_if and p.get("enabled") is False:
            warnings.append(
                LockoutWarning(
                    op_index=idx,
                    op_type=op.op,
                    message=(
                        f"This op disables the management interface "
                        f"({management_if}). You will lose access."
                    ),
                )
            )
        if p.get("opn_if_name") == management_if and "ipv4" in p:
            warnings.append(
                LockoutWarning(
                    op_index=idx,
                    op_type=op.op,
                    message=(
                        f"This op changes the IP of the management interface "
                        f"({management_if}). Reachability will likely break."
                    ),
                )
            )

    if op.op == "service.disable":
        name = p.get("name", "").lower()
        if name in _DANGEROUS_SERVICES:
            warnings.append(
                LockoutWarning(
                    op_index=idx,
                    op_type=op.op,
                    message=(
                        f"Disabling service {name!r} would block management access "
                        "(SSH or web/API)."
                    ),
                )
            )

    if op.op == "rule.delete":
        # Best-effort: warn if a rule's source includes self_ip.
        # The actual check requires looking at the rule, which we'd do
        # by fetching it from the API in a richer impl. For v1, warn on any delete.
        warnings.append(
            LockoutWarning(
                op_index=idx,
                op_type=op.op,
                message=(
                    f"Rule deletion can break management access. Verify the rule "
                    f"being deleted does not allow your IP ({self_ip})."
                ),
            )
        )

    return warnings


def check_plan(plan: Plan, *, self_ip: str, management_if: str) -> list[LockoutWarning]:
    """Return all lockout warnings for the plan; empty list = safe."""
    warnings: list[LockoutWarning] = []
    for idx, op in enumerate(plan.ops):
        warnings.extend(_check_op(op, idx, self_ip=self_ip, management_if=management_if))
    return warnings
