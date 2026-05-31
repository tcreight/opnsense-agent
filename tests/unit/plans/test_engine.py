from __future__ import annotations

import pytest

from opnsense_agent.plans.engine import (
    HandlerContext,
    OpHandlerRegistry,
    UnknownOpError,
)
from opnsense_agent.plans.schema import OpResult, PlanOp


class FakeHandler:
    op_type = "test.echo"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        return OpResult(op=op.op, status="ok", response={"echoed": op.params})


def test_register_and_lookup() -> None:
    registry = OpHandlerRegistry()
    registry.register(FakeHandler())
    assert registry.get("test.echo").op_type == "test.echo"


def test_unknown_op_raises() -> None:
    registry = OpHandlerRegistry()
    with pytest.raises(UnknownOpError):
        registry.get("does.not.exist")


def test_double_register_raises() -> None:
    registry = OpHandlerRegistry()
    registry.register(FakeHandler())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeHandler())
