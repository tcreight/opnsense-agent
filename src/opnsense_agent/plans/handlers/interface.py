"""Handlers for interface.assign and interface.configure ops."""

from __future__ import annotations

import logging

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.schema import OpResult, PlanOp

logger = logging.getLogger(__name__)


class InterfaceAssignHandler:
    op_type = "interface.assign"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        params = op.params
        body = {
            "interface": {
                "if": f"{params['parent_if']}_vlan{params['vlan_tag']}",
                "descr": params.get("opn_if_name", ""),
                "enable": "1" if params.get("enabled", True) else "0",
            }
        }
        try:
            response = await ctx.api.post(
                f"/api/interfaces/settings/setItem/{params['opn_if_name']}",
                json=body,
            )
            if response.get("result") not in {"saved", "ok"}:
                return OpResult(
                    op=op.op,
                    status="error",
                    response=response,
                    error=f"assign failed: {response}",
                )
            await ctx.api.post("/api/interfaces/settings/reconfigure", json={})
            return OpResult(op=op.op, status="ok", response=response)
        except Exception as e:  # noqa: BLE001
            logger.exception("interface.assign failed")
            return OpResult(op=op.op, status="error", error=str(e))


class InterfaceConfigureHandler:
    op_type = "interface.configure"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        params = op.params
        body = {
            "interface": {
                "ipaddr": params["ipv4"],
                "subnet": str(params["ipv4_subnet"]),
                "ipaddrv6": params.get("ipv6", ""),
            }
        }
        try:
            response = await ctx.api.post(
                f"/api/interfaces/settings/setItem/{params['opn_if_name']}",
                json=body,
            )
            if response.get("result") not in {"saved", "ok"}:
                return OpResult(
                    op=op.op,
                    status="error",
                    response=response,
                    error=f"configure failed: {response}",
                )
            await ctx.api.post("/api/interfaces/settings/reconfigure", json={})
            return OpResult(op=op.op, status="ok", response=response)
        except Exception as e:  # noqa: BLE001
            logger.exception("interface.configure failed")
            return OpResult(op=op.op, status="error", error=str(e))
