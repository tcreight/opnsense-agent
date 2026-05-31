from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.handlers.dhcp import DhcpScopeCreateHandler, DhcpStaticAddHandler
from opnsense_agent.plans.schema import PlanOp


@pytest.mark.asyncio
async def test_scope_create_posts_addSubnet_then_reconfigure() -> None:
    api = AsyncMock()
    api.post.side_effect = [
        {"result": "saved", "uuid": "subnet-uuid-1"},
        {"status": "ok"},
    ]
    handler = DhcpScopeCreateHandler()
    op = PlanOp(
        op="dhcp.scope.create",
        params={
            "interface": "opt3",
            "range_from": "10.30.0.100",
            "range_to": "10.30.0.200",
            "router": "10.30.0.1",
            "dns": ["10.30.0.1"],
            "subnet": "10.30.0.0/24",
        },
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
    assert api.post.call_count == 2


@pytest.mark.asyncio
async def test_static_add_posts_addReservation() -> None:
    api = AsyncMock()
    api.post.side_effect = [
        {"result": "saved", "uuid": "res-1"},
        {"status": "ok"},
    ]
    handler = DhcpStaticAddHandler()
    op = PlanOp(
        op="dhcp.static.add",
        params={
            "interface": "opt3",
            "mac": "aa:bb:cc:dd:ee:ff",
            "ip": "10.30.0.50",
            "hostname": "thermostat",
        },
    )
    ctx = HandlerContext(api=api, ssh=AsyncMock())
    result = await handler.execute(op, ctx)
    assert result.status == "ok"
