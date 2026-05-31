"""Op handler protocol, registry, and the plan apply pipeline."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from opnsense_agent.plans.schema import OpResult, PlanOp, PlanStatus
from opnsense_agent.plans.store import PlanStore
from opnsense_agent.safety import lockout

if TYPE_CHECKING:
    from opnsense_agent.client.api import OpnApiClient
    from opnsense_agent.client.ssh import OpnSshClient

logger = logging.getLogger(__name__)


class UnknownOpError(Exception):
    """Raised when no handler is registered for a given op type."""


@dataclass(frozen=True)
class HandlerContext:
    """Resources available to a handler during execution."""

    api: OpnApiClient
    ssh: OpnSshClient


@runtime_checkable
class OpHandler(Protocol):
    op_type: str

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult: ...


class OpHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, OpHandler] = {}

    def register(self, handler: OpHandler) -> None:
        if handler.op_type in self._handlers:
            raise ValueError(f"Op type {handler.op_type!r} already registered")
        self._handlers[handler.op_type] = handler
        logger.debug("Registered op handler: %s", handler.op_type)

    def get(self, op_type: str) -> OpHandler:
        try:
            return self._handlers[op_type]
        except KeyError as e:
            raise UnknownOpError(f"No handler for op type: {op_type!r}") from e

    def known_types(self) -> list[str]:
        return sorted(self._handlers.keys())


# === Apply pipeline ===


class _BackupProto(Protocol):
    async def create(self, api: OpnApiClient, label: str | None = None) -> str: ...
    async def restore(self, api: OpnApiClient, backup_id: str) -> None: ...


@dataclass(frozen=True)
class PlanApplyResult:
    plan_id: str
    status: PlanStatus
    backup_id: str | None
    rollback_reason: str | None
    op_results: list[OpResult]


class PlanApplyPipeline:
    """The single chokepoint for all mutations.

    Pipeline:
      1. Lockout check (warnings -> require override or fail)
      2. Backup
      3. Sequential op execution (stop on first failure)
      4. Reachability probe
      5. Finalize plan status; on failure or probe failure, restore backup
    """

    def __init__(
        self,
        *,
        store: PlanStore,
        registry: OpHandlerRegistry,
        backup: _BackupProto,
        api: OpnApiClient,
        ssh: OpnSshClient,
        probe: Callable[..., Awaitable[bool]],
        self_ip: str,
        management_if: str,
        allow_lockout_override: bool = True,
    ) -> None:
        self._store = store
        self._registry = registry
        self._backup = backup
        self._api = api
        self._ssh = ssh
        self._probe = probe
        self._self_ip = self_ip
        self._management_if = management_if
        self._allow_lockout_override = allow_lockout_override

    async def apply(
        self,
        plan_id: str,
        *,
        confirm: bool,
        override_lockout: bool = False,
    ) -> PlanApplyResult:
        if not confirm:
            raise PermissionError(
                "apply requires confirm=True. The /opn-apply slash command "
                "handles this; do not call apply directly."
            )

        plan = self._store.load(plan_id)
        if plan.status is not PlanStatus.draft:
            raise ValueError(
                f"Plan {plan_id} status is {plan.status.value}; only drafts can be applied."
            )

        warnings = lockout.check_plan(
            plan, self_ip=self._self_ip, management_if=self._management_if
        )
        if warnings and not override_lockout:
            if not self._allow_lockout_override:
                raise PermissionError(
                    f"Lockout check produced {len(warnings)} warning(s) and override "
                    "is disabled in safety config."
                )
            return PlanApplyResult(
                plan_id=plan.plan_id,
                status=PlanStatus.draft,
                backup_id=None,
                rollback_reason=(
                    f"Lockout warnings: {[w.message for w in warnings]} (override required)"
                ),
                op_results=[],
            )

        backup_id = await self._backup.create(api=self._api, label=f"pre-apply-{plan.plan_id}")

        ctx = HandlerContext(api=self._api, ssh=self._ssh)
        results: list[OpResult] = []
        had_failure = False

        for op in plan.ops:
            handler = self._registry.get(op.op)
            result = await handler.execute(op, ctx)
            results.append(result)
            if result.status != "ok":
                had_failure = True
                logger.error("Op failed: %s — %s", op.op, result.error)
                break

        if had_failure:
            await self._backup.restore(api=self._api, backup_id=backup_id)
            final = plan.model_copy(
                update={
                    "status": PlanStatus.failed,
                    "execution": plan.execution.model_copy(
                        update={
                            "backup_id": backup_id,
                            "applied_at": datetime.now(UTC),
                            "results": results,
                            "rollback_reason": "op execution failed",
                        }
                    ),
                }
            )
            self._store.finalize(final)
            return PlanApplyResult(
                plan_id=plan.plan_id,
                status=PlanStatus.failed,
                backup_id=backup_id,
                rollback_reason="op execution failed",
                op_results=results,
            )

        probe_ok = await self._probe(api=self._api)
        if not probe_ok:
            await self._backup.restore(api=self._api, backup_id=backup_id)
            final = plan.model_copy(
                update={
                    "status": PlanStatus.rolled_back,
                    "execution": plan.execution.model_copy(
                        update={
                            "backup_id": backup_id,
                            "applied_at": datetime.now(UTC),
                            "results": results,
                            "rollback_reason": "post-apply reachability probe failed",
                        }
                    ),
                }
            )
            self._store.finalize(final)
            return PlanApplyResult(
                plan_id=plan.plan_id,
                status=PlanStatus.rolled_back,
                backup_id=backup_id,
                rollback_reason="post-apply reachability probe failed",
                op_results=results,
            )

        final = plan.model_copy(
            update={
                "status": PlanStatus.applied,
                "execution": plan.execution.model_copy(
                    update={
                        "backup_id": backup_id,
                        "applied_at": datetime.now(UTC),
                        "results": results,
                    }
                ),
            }
        )
        self._store.finalize(final)
        self._append_audit(
            plan_id=plan.plan_id,
            action="apply",
            backup_id=backup_id,
            status=PlanStatus.applied,
        )
        return PlanApplyResult(
            plan_id=plan.plan_id,
            status=PlanStatus.applied,
            backup_id=backup_id,
            rollback_reason=None,
            op_results=results,
        )

    def _append_audit(
        self,
        *,
        plan_id: str,
        action: str,
        backup_id: str | None,
        status: PlanStatus,
    ) -> None:
        audit_path = self._store.runs_dir / "audit.log"
        line = (
            f"{datetime.now(UTC).isoformat()} "
            f"action={action} plan_id={plan_id} backup_id={backup_id} "
            f"status={status.value}\n"
        )
        with audit_path.open("a") as f:
            f.write(line)
