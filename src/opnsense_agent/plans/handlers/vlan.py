"""Handler for vlan.create op."""

from __future__ import annotations

import logging

from opnsense_agent.plans.engine import HandlerContext
from opnsense_agent.plans.schema import OpResult, PlanOp

logger = logging.getLogger(__name__)


class VlanCreateHandler:
    op_type = "vlan.create"

    async def execute(self, op: PlanOp, ctx: HandlerContext) -> OpResult:
        params = op.params
        body = {
            "vlan": {
                "tag": str(params["tag"]),
                "if": params["parent_if"],
                "descr": params.get("description", ""),
                "pcp": str(params.get("pcp", 0)),
            }
        }
        try:
            add = await ctx.api.post("/api/interfaces/vlan_settings/addItem", json=body)
            if add.get("result") != "saved":
                return OpResult(
                    op=op.op,
                    status="error",
                    response=add,
                    error=f"addItem failed: {add.get('validations') or add}",
                )
            reconfigure = await ctx.api.post("/api/interfaces/vlan_settings/reconfigure", json={})
            return OpResult(
                op=op.op,
                status="ok",
                response={"add": add, "reconfigure": reconfigure},
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("vlan.create failed")
            return OpResult(op=op.op, status="error", error=str(e))
