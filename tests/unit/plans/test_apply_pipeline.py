from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from opnsense_agent.plans.engine import (
    OpHandlerRegistry,
    PlanApplyPipeline,
    PlanApplyResult,
)
from opnsense_agent.plans.schema import (
    Plan,
    PlanOp,
    PlanStatus,
    PlanTarget,
)
from opnsense_agent.plans.store import PlanStore


def _plan() -> Plan:
    return Plan(
        plan_id="t1",
        description="test",
        created=datetime.now(UTC),
        target=PlanTarget(host="opnsense.test"),
        ops=[PlanOp(op="vlan.create", params={"tag": 30, "parent_if": "igb1"})],
    )


class _OkHandler:
    op_type = "vlan.create"

    async def execute(self, op, ctx):  # type: ignore[no-untyped-def]
        from opnsense_agent.plans.schema import OpResult

        return OpResult(op=op.op, status="ok", response={"r": 1})


class _FailHandler:
    op_type = "vlan.create"

    async def execute(self, op, ctx):  # type: ignore[no-untyped-def]
        from opnsense_agent.plans.schema import OpResult

        return OpResult(op=op.op, status="error", error="boom")


@pytest.mark.asyncio
async def test_apply_happy_path(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_OkHandler())

    probe = AsyncMock(return_value=True)
    api = AsyncMock()
    ssh = AsyncMock()

    pipeline = PlanApplyPipeline(
        store=store,
        registry=registry,
        backup=backup,
        api=api,
        ssh=ssh,
        probe=probe,
        self_ip="10.0.0.50",
        management_if="igb0",
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)
    assert isinstance(result, PlanApplyResult)
    assert result.status is PlanStatus.applied
    assert result.backup_id == "bk-1"
    assert backup.restore.await_count == 0


@pytest.mark.asyncio
async def test_apply_op_failure_triggers_rollback(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_FailHandler())

    probe = AsyncMock(return_value=True)
    api = AsyncMock()
    ssh = AsyncMock()

    pipeline = PlanApplyPipeline(
        store=store,
        registry=registry,
        backup=backup,
        api=api,
        ssh=ssh,
        probe=probe,
        self_ip="10.0.0.50",
        management_if="igb0",
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)
    assert result.status is PlanStatus.failed
    assert backup.restore.await_count == 1


@pytest.mark.asyncio
async def test_apply_probe_failure_triggers_rollback(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)

    backup = AsyncMock()
    backup.create.return_value = "bk-1"

    registry = OpHandlerRegistry()
    registry.register(_OkHandler())

    probe = AsyncMock(return_value=False)
    api = AsyncMock()
    ssh = AsyncMock()

    pipeline = PlanApplyPipeline(
        store=store,
        registry=registry,
        backup=backup,
        api=api,
        ssh=ssh,
        probe=probe,
        self_ip="10.0.0.50",
        management_if="igb0",
    )
    result = await pipeline.apply(plan.plan_id, confirm=True)
    assert result.status is PlanStatus.rolled_back
    assert backup.restore.await_count == 1


@pytest.mark.asyncio
async def test_apply_refuses_without_confirm(tmp_path: Path) -> None:
    plan = _plan()
    store = PlanStore(runs_dir=tmp_path)
    store.save(plan)
    pipeline = PlanApplyPipeline(
        store=store,
        registry=OpHandlerRegistry(),
        backup=AsyncMock(),
        api=AsyncMock(),
        ssh=AsyncMock(),
        probe=AsyncMock(),
        self_ip="x",
        management_if="x",
    )
    with pytest.raises(PermissionError, match="confirm"):
        await pipeline.apply(plan.plan_id, confirm=False)
