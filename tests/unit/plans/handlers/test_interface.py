from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.handlers.interface import (
    InterfaceAssignHandler,
    InterfaceConfigureHandler,
)
from opnsense_agent.plans.schema import PlanOp


@pytest.mark.asyncio
async def test_assign_posts_to_interface_settings() -> None:
    api = AsyncMock()
    api.post.return_value = {"result": "saved"}
    handler = InterfaceAssignHandler()
    op = PlanOp(
        op="interface.assign",
        params={
            "vlan_tag": 30,
            "parent_if": "igb1",
            "opn_if_name": "opt3",
            "enabled": True,
        },
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
    assert api.post.called


@pytest.mark.asyncio
async def test_configure_sets_ipv4() -> None:
    api = AsyncMock()
    api.post.return_value = {"result": "saved"}
    handler = InterfaceConfigureHandler()
    op = PlanOp(
        op="interface.configure",
        params={
            "opn_if_name": "opt3",
            "ipv4": "10.30.0.1",
            "ipv4_subnet": 24,
        },
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
    # First call is setItem (carries the body); second is reconfigure with {}.
    body = api.post.call_args_list[0].kwargs["json"]
    assert body["interface"]["ipaddr"] == "10.30.0.1"
    assert body["interface"]["subnet"] == "24"
