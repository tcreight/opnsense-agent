"""Op handler protocol, registry, and the plan apply pipeline.

CHOKEPOINT INVARIANT
--------------------
All mutating interactions with the OPNsense firewall MUST funnel through
``PlanApplyPipeline.apply()``. No other code path may call
``OpnApiClient.post()`` to mutate config, nor invoke an ``OpHandler``
directly. The pipeline owns lockout-checking, backup-then-restore, and
audit logging — bypassing it loses those guarantees.

If you need a new mutation path (slash command, MCP tool, CLI), wire it
to construct a ``Plan`` and call ``PlanApplyPipeline.apply()``. Do not
add a parallel mutation route.

Reads (``api.get``, SSH diagnostic commands) are unrestricted.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from opnsense_agent.plans.schema import OpResult, Plan, PlanOp, PlanStatus
from opnsense_agent.plans.store import PlanStore
from opnsense_agent.safety import lockout

if TYPE_CHECKING:
    from opnsense_agent.client.api import OpnApiClient
    from opnsense_agent.client.ssh import OpnSshClient

logger = logging.getLogger(__name__)


class UnknownOpError(Exception):
    """Raised when no handler is registered for a given op type."""


class ApplyInProgressError(Exception):
    """Raised when apply() is called while another mutation holds the lock.

    Fail-fast instead of queueing: a silently queued apply would block past
    the MCP client's tool timeout and then mutate state its caller never
    previewed (the running apply changes the config underneath it).
    """


class LockoutCheckFailedError(Exception):
    """Raised by the apply pipeline when a plan triggers one or more lockout
    warnings and the caller did not opt in to overriding them.

    Carries the full list of ``LockoutWarning`` records so the caller can
    present them to the operator before retrying with ``override_lockout=True``.
    """

    def __init__(self, warnings: Sequence[lockout.LockoutWarning]) -> None:
        self.warnings: list[lockout.LockoutWarning] = list(warnings)
        super().__init__(
            f"Plan triggered {len(self.warnings)} lockout warning(s); "
            "pass override_lockout=True to apply anyway."
        )


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
      1. Lockout check (warnings -> raise LockoutCheckFailedError unless overridden)
      2. Backup
      3. Sequential op execution (stop on first failure; handler exceptions
         are caught and treated as op failures)
      4. Reachability probe
      5. Finalize plan status; on op failure or probe failure, restore backup
         (catastrophic restore failures are themselves caught and recorded
         in rollback_reason rather than escaping the pipeline)
      6. Audit log line written for every terminal state (applied, failed,
         rolled_back)

    Defaults to fail-closed: ``allow_lockout_override=False`` means even an
    explicit ``override_lockout=True`` from the caller is rejected with
    ``PermissionError``. Set ``True`` only when the safety config opts in.
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
        allow_lockout_override: bool = False,
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
        # The MCP server is async: concurrent opn_plan_apply tool calls could
        # interleave backup/op/probe/rollback steps, so applies are serialized.
        self._apply_lock = asyncio.Lock()

    @property
    def mutation_lock(self) -> asyncio.Lock:
        """The lock serializing ALL config mutations.

        apply() holds it for its full duration; the MCP server's manual
        backup-restore path acquires it too, so a restore can never interleave
        with an in-flight apply.
        """
        return self._apply_lock

    async def apply(
        self,
        plan_id: str,
        *,
        confirm: bool,
        override_lockout: bool = False,
    ) -> PlanApplyResult:
        # Fail fast rather than queue: locked() then acquire is racy in
        # general, but the async-with below still serializes correctly — the
        # check only exists to reject the common case with a clear error.
        if self._apply_lock.locked():
            raise ApplyInProgressError(
                "Another apply or restore is in progress; retry after it completes."
            )
        # Hold the lock for the entire apply so two concurrent applies can
        # never interleave their backup/op/probe/rollback steps.
        async with self._apply_lock:
            return await self._apply_locked(
                plan_id, confirm=confirm, override_lockout=override_lockout
            )

    async def _apply_locked(
        self,
        plan_id: str,
        *,
        confirm: bool,
        override_lockout: bool,
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
        if warnings:
            if not override_lockout:
                raise LockoutCheckFailedError(warnings)
            if not self._allow_lockout_override:
                raise PermissionError(
                    f"Lockout check produced {len(warnings)} warning(s) and override "
                    "is disabled in safety config (allow_lockout_override=False)."
                )

        backup_id = await self._backup.create(api=self._api, label=f"pre-apply-{plan.plan_id}")

        ctx = HandlerContext(api=self._api, ssh=self._ssh)
        results: list[OpResult] = []
        had_failure = False

        for op in plan.ops:
            result = await self._execute_one_op(op, ctx)
            results.append(result)
            if result.status != "ok":
                had_failure = True
                logger.error("Op failed: %s — %s", op.op, result.error)
                break

        if had_failure:
            rollback_reason = await self._safe_restore(backup_id, base_reason="op execution failed")
            return self._finalize_and_audit(
                plan=plan,
                status=PlanStatus.failed,
                backup_id=backup_id,
                rollback_reason=rollback_reason,
                results=results,
            )

        probe_ok = await self._probe(api=self._api)
        if not probe_ok:
            rollback_reason = await self._safe_restore(
                backup_id, base_reason="post-apply reachability probe failed"
            )
            return self._finalize_and_audit(
                plan=plan,
                status=PlanStatus.rolled_back,
                backup_id=backup_id,
                rollback_reason=rollback_reason,
                results=results,
            )

        return self._finalize_and_audit(
            plan=plan,
            status=PlanStatus.applied,
            backup_id=backup_id,
            rollback_reason=None,
            results=results,
        )

    async def _execute_one_op(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        """Run a single op handler with full exception containment.

        An uncaught exception inside a handler (or an unknown op type) would
        otherwise escape apply() and leave the plan stuck in draft with no
        rollback and no audit entry. We synthesize an OpResult instead so the
        normal failure-then-rollback path runs.
        """
        try:
            handler = self._registry.get(op.op)
        except UnknownOpError as e:
            return OpResult(op=op.op, status="error", error=str(e))
        try:
            return await handler.execute(op, ctx)
        except Exception as e:  # noqa: BLE001 — handlers are external code
            logger.exception("Handler raised for op %s", op.op)
            return OpResult(op=op.op, status="error", error=f"handler raised: {e}")

    async def _safe_restore(self, backup_id: str, *, base_reason: str) -> str:
        """Attempt backup restore; never raise.

        If restore itself fails, augment the rollback reason so the operator
        knows the firewall may be in an inconsistent state and the prior
        config XML is available at ``runs/backups/<backup_id>.xml`` for
        manual recovery.
        """
        try:
            await self._backup.restore(api=self._api, backup_id=backup_id)
            return base_reason
        except Exception as e:  # noqa: BLE001
            logger.exception("Backup restore FAILED for backup_id=%s", backup_id)
            return (
                f"{base_reason}; backup restore ALSO failed: {e}. "
                f"Prior config preserved at runs/backups/{backup_id}.xml"
            )

    def _finalize_and_audit(
        self,
        *,
        plan: Plan,
        status: PlanStatus,
        backup_id: str | None,
        rollback_reason: str | None,
        results: list[OpResult],
    ) -> PlanApplyResult:
        exec_update: dict[str, object] = {
            "backup_id": backup_id,
            "applied_at": datetime.now(UTC),
            "results": results,
        }
        if rollback_reason is not None:
            exec_update["rollback_reason"] = rollback_reason
        final = plan.model_copy(
            update={
                "status": status,
                "execution": plan.execution.model_copy(update=exec_update),
            }
        )
        self._store.finalize(final)
        self._append_audit(
            plan_id=plan.plan_id,
            action="apply",
            backup_id=backup_id,
            status=status,
            rollback_reason=rollback_reason,
        )
        return PlanApplyResult(
            plan_id=plan.plan_id,
            status=status,
            backup_id=backup_id,
            rollback_reason=rollback_reason,
            op_results=results,
        )

    def _append_audit(
        self,
        *,
        plan_id: str,
        action: str,
        backup_id: str | None,
        status: PlanStatus,
        rollback_reason: str | None = None,
    ) -> None:
        audit_path = self._store.runs_dir / "audit.log"
        parts = [
            datetime.now(UTC).isoformat(),
            f"action={action}",
            f"plan_id={plan_id}",
            f"backup_id={backup_id}",
            f"status={status.value}",
        ]
        if rollback_reason:
            # Quote and replace embedded quotes/newlines so a single audit line
            # stays a single grep-friendly line. Not a JSON document — just
            # enough escaping to survive operator tooling.
            escaped = rollback_reason.replace('"', "'").replace("\n", " ")
            parts.append(f'rollback_reason="{escaped}"')
        with audit_path.open("a") as f:
            f.write(" ".join(parts) + "\n")
