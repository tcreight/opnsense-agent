from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from opnsense_agent.plans.engine import (
    HandlerContext,
    LockoutCheckFailedError,
    OpHandlerRegistry,
    PlanApplyPipeline,
    PlanApplyResult,
    _BackupProto,  # pyright: ignore[reportPrivateUsage] — test references the pipeline's backup contract
)
from opnsense_agent.plans.schema import (
    OpResult,
    Plan,
    PlanOp,
    PlanStatus,
    PlanTarget,
)
from opnsense_agent.plans.store import PlanStore


def _plan(ops: list[PlanOp] | None = None) -> Plan:
    return Plan(
        plan_id="t1",
        description="test",
        created=datetime.now(UTC),
        target=PlanTarget(host="opnsense.test"),
        ops=ops or [PlanOp(op="vlan.create", params={"tag": 30, "parent_if": "igb1"})],
    )


class _OkHandler:
    op_type = "vlan.create"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        return OpResult(op=op.op, status="ok", response={"r": 1})


class _FailHandler:
    op_type = "vlan.create"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        return OpResult(op=op.op, status="error", error="boom")


class _RaisingHandler:
    op_type = "vlan.create"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        raise RuntimeError("handler exploded")


class _ServiceDisableOkHandler:
    """Used by tests that trigger a lockout warning then override."""

    op_type = "service.disable"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        return OpResult(op=op.op, status="ok")


def _audit_lines(tmp_path: Path) -> list[str]:
    audit = tmp_path / "audit.log"
    if not audit.exists():
        return []
    return [ln for ln in audit.read_text().splitlines() if ln.strip()]


def _make_pipeline(
    *,
    store: PlanStore,
    registry: OpHandlerRegistry,
    backup: _BackupProto,
    probe: Callable[..., Awaitable[bool]],
    allow_lockout_override: bool = False,
) -> PlanApplyPipeline:
    return PlanApplyPipeline(
        store=store,
        registry=registry,
        backup=backup,
        api=AsyncMock(),
        ssh=AsyncMock(),
        probe=probe,
        self_ip="10.0.0.50",
        management_if="igb0",
        allow_lockout_override=allow_lockout_override,
    )


# ─────────────── Happy / failure / probe-failure paths ───────────────


@pytest.mark.asyncio
async def test_apply_happy_path(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_OkHandler())

    pipeline = _make_pipeline(
        store=store,
        registry=registry,
        backup=backup,
        probe=AsyncMock(return_value=True),
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)

    assert isinstance(result, PlanApplyResult)
    assert result.status is PlanStatus.applied
    assert result.backup_id == "bk-1"
    assert backup.restore.await_count == 0

    # On-disk plan must be finalized as applied with the right backup id.
    loaded = store.load(plan.plan_id)
    assert loaded.status is PlanStatus.applied
    assert loaded.execution.backup_id == "bk-1"
    assert loaded.execution.applied_at is not None

    # Audit log must record the apply.
    lines = _audit_lines(tmp_path)
    assert len(lines) == 1
    assert "status=applied" in lines[0]
    assert "plan_id=t1" in lines[0]


@pytest.mark.asyncio
async def test_apply_op_failure_triggers_rollback(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_FailHandler())

    pipeline = _make_pipeline(
        store=store,
        registry=registry,
        backup=backup,
        probe=AsyncMock(return_value=True),
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)

    assert result.status is PlanStatus.failed
    assert backup.restore.await_count == 1

    loaded = store.load(plan.plan_id)
    assert loaded.status is PlanStatus.failed
    assert loaded.execution.backup_id == "bk-1"

    lines = _audit_lines(tmp_path)
    assert len(lines) == 1
    assert "status=failed" in lines[0]


@pytest.mark.asyncio
async def test_apply_probe_failure_triggers_rollback(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_OkHandler())

    pipeline = _make_pipeline(
        store=store,
        registry=registry,
        backup=backup,
        probe=AsyncMock(return_value=False),
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)

    assert result.status is PlanStatus.rolled_back
    assert backup.restore.await_count == 1

    loaded = store.load(plan.plan_id)
    assert loaded.status is PlanStatus.rolled_back

    lines = _audit_lines(tmp_path)
    assert len(lines) == 1
    assert "status=rolled_back" in lines[0]


# ─────────────── confirm guard ───────────────


@pytest.mark.asyncio
async def test_apply_refuses_without_confirm(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)
    pipeline = _make_pipeline(
        store=store,
        registry=OpHandlerRegistry(),
        backup=AsyncMock(),
        probe=AsyncMock(),
    )
    with pytest.raises(PermissionError, match="confirm"):
        await pipeline.apply(plan.plan_id, confirm=False)


# ─────────────── Lockout semantics (CR-1 + CR-2) ───────────────


@pytest.mark.asyncio
async def test_apply_with_warnings_raises_lockout_check_failed(tmp_path: Path) -> None:
    """Default behaviour: a plan that triggers lockout warnings must raise,
    not silently no-op with a confusing 'draft' result."""
    plan = _plan(ops=[PlanOp(op="service.disable", params={"name": "openssh"})])
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)
    pipeline = _make_pipeline(
        store=store,
        registry=OpHandlerRegistry(),
        backup=AsyncMock(),
        probe=AsyncMock(return_value=True),
    )
    with pytest.raises(LockoutCheckFailedError) as excinfo:
        await pipeline.apply(plan.plan_id, confirm=True)
    assert len(excinfo.value.warnings) >= 1
    assert any("ssh" in w.message.lower() for w in excinfo.value.warnings)


@pytest.mark.asyncio
async def test_apply_warnings_proceeds_when_override_allowed(tmp_path: Path) -> None:
    """override_lockout=True bypasses the raise iff allow_lockout_override=True."""
    plan = _plan(ops=[PlanOp(op="service.disable", params={"name": "openssh"})])
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)
    backup = AsyncMock()
    backup.create.return_value = "bk-1"
    registry = OpHandlerRegistry()
    registry.register(_ServiceDisableOkHandler())

    pipeline = _make_pipeline(
        store=store,
        registry=registry,
        backup=backup,
        probe=AsyncMock(return_value=True),
        allow_lockout_override=True,
    )
    result = await pipeline.apply(plan.plan_id, confirm=True, override_lockout=True)
    assert result.status is PlanStatus.applied


@pytest.mark.asyncio
async def test_apply_warnings_with_override_disabled_in_safety_raises(tmp_path: Path) -> None:
    """If allow_lockout_override=False (config-level kill switch), even an
    explicit override_lockout=True from the caller raises PermissionError."""
    plan = _plan(ops=[PlanOp(op="service.disable", params={"name": "openssh"})])
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)
    pipeline = _make_pipeline(
        store=store,
        registry=OpHandlerRegistry(),
        backup=AsyncMock(),
        probe=AsyncMock(),
        allow_lockout_override=False,
    )
    with pytest.raises(PermissionError, match="override"):
        await pipeline.apply(plan.plan_id, confirm=True, override_lockout=True)


# ─────────────── Failure-path guards (CR-2) ───────────────


@pytest.mark.asyncio
async def test_apply_handler_raising_is_caught_and_rolls_back(tmp_path: Path) -> None:
    """A handler raising an unexpected exception must NOT escape apply().
    It must produce a synthetic OpResult, restore the backup, finalize, audit."""
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_RaisingHandler())

    pipeline = _make_pipeline(
        store=store,
        registry=registry,
        backup=backup,
        probe=AsyncMock(return_value=True),
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)

    assert result.status is PlanStatus.failed
    assert backup.restore.await_count == 1
    assert result.op_results[0].status == "error"
    assert "exploded" in (result.op_results[0].error or "")

    loaded = store.load(plan.plan_id)
    assert loaded.status is PlanStatus.failed

    assert any("status=failed" in ln for ln in _audit_lines(tmp_path))


@pytest.mark.asyncio
async def test_apply_unknown_op_is_caught_and_rolls_back(tmp_path: Path) -> None:
    """A plan op with no registered handler must not crash the pipeline."""
    plan = _plan(ops=[PlanOp(op="totally.unregistered", params={})])
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    pipeline = _make_pipeline(
        store=store,
        registry=OpHandlerRegistry(),
        backup=backup,
        probe=AsyncMock(return_value=True),
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)

    assert result.status is PlanStatus.failed
    assert backup.restore.await_count == 1
    assert "totally.unregistered" in (result.op_results[0].error or "")


@pytest.mark.asyncio
async def test_apply_restore_failure_is_still_finalized_and_audited(tmp_path: Path) -> None:
    """If backup.restore itself fails, the pipeline must still finalize the plan
    as failed, augment rollback_reason, and write an audit line. This is the
    worst case and the one that most needs a paper trail."""
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"
    backup.restore.side_effect = RuntimeError("config api unreachable")

    registry = OpHandlerRegistry()
    registry.register(_FailHandler())

    pipeline = _make_pipeline(
        store=store,
        registry=registry,
        backup=backup,
        probe=AsyncMock(return_value=True),
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)

    assert result.status is PlanStatus.failed
    assert "ALSO failed" in (result.rollback_reason or "")
    assert "config api unreachable" in (result.rollback_reason or "")

    loaded = store.load(plan.plan_id)
    assert loaded.status is PlanStatus.failed
    assert "ALSO failed" in (loaded.execution.rollback_reason or "")

    lines = _audit_lines(tmp_path)
    assert any("status=failed" in ln for ln in lines)
    assert any("ALSO failed" in ln for ln in lines)
