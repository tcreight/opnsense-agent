from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.handlers.vlan import VlanCreateHandler
from opnsense_agent.plans.schema import PlanOp


@pytest.mark.asyncio
async def test_vlan_create_calls_addItem_then_reconfigure() -> None:  # noqa: N802
    api = AsyncMock()
    api.post.side_effect = [
        {"result": "saved", "uuid": "vlan-uuid-1"},  # addItem
        {"status": "ok"},  # reconfigure
    ]
    handler = VlanCreateHandler()
    op = PlanOp(
        op="vlan.create",
        params={"tag": 30, "parent_if": "igb1", "description": "IoT"},
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
    assert api.post.call_count == 2
    add_call, reconfig_call = api.post.call_args_list
    assert add_call.args[0] == "/api/interfaces/vlan_settings/addItem"
    assert reconfig_call.args[0] == "/api/interfaces/vlan_settings/reconfigure"
    body = add_call.kwargs["json"]
    assert body["vlan"]["tag"] == "30"
    assert body["vlan"]["if"] == "igb1"
    assert body["vlan"]["descr"] == "IoT"


@pytest.mark.asyncio
async def test_vlan_create_handles_addItem_failure() -> None:  # noqa: N802
    api = AsyncMock()
    api.post.side_effect = [
        {"result": "failed", "validations": {"vlan.tag": "invalid"}},
    ]
    handler = VlanCreateHandler()
    op = PlanOp(op="vlan.create", params={"tag": 5000, "parent_if": "igb1"})
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "error"
    assert "invalid" in (result.error or "")
    # Did NOT call reconfigure after a failed add
    assert api.post.call_count == 1
