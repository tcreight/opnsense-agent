"""Handlers for dhcp.scope.create and dhcp.static.add ops (Kea backend)."""

from __future__ import annotations

import logging

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.schema import OpResult, PlanOp

logger = logging.getLogger(__name__)


class DhcpScopeCreateHandler:
    op_type = "dhcp.scope.create"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        p = op.params
        body = {
            "subnet4": {
                "subnet": p["subnet"],
                "pools": f"{p['range_from']}-{p['range_to']}",
                "option_data_router": p["router"],
                "option_data_domain_name_servers": ",".join(p["dns"]),
                "interface": p["interface"],
            }
        }
        try:
            add = await ctx.api.post("/api/kea/dhcpv4/addSubnet", json=body)
            if add.get("result") != "saved":
                return OpResult(
                    op=op.op,
                    status="error",
                    response=add,
                    error=f"addSubnet failed: {add}",
                )
            reconf = await ctx.api.post("/api/kea/service/reconfigure", json={})
            return OpResult(
                op=op.op,
                status="ok",
                response={"add": add, "reconfigure": reconf},
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("dhcp.scope.create failed")
            return OpResult(op=op.op, status="error", error=str(e))


class DhcpStaticAddHandler:
    op_type = "dhcp.static.add"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        p = op.params
        body = {
            "reservation": {
                "subnet": p["interface"],
                "ip_address": p["ip"],
                "hw_address": p["mac"],
                "hostname": p.get("hostname", ""),
            }
        }
        try:
            add = await ctx.api.post("/api/kea/dhcpv4/addReservation", json=body)
            if add.get("result") != "saved":
                return OpResult(
                    op=op.op,
                    status="error",
                    response=add,
                    error=f"addReservation failed: {add}",
                )
            reconf = await ctx.api.post("/api/kea/service/reconfigure", json={})
            return OpResult(
                op=op.op,
                status="ok",
                response={"add": add, "reconfigure": reconf},
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("dhcp.static.add failed")
            return OpResult(op=op.op, status="error", error=str(e))
