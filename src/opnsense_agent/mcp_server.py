"""MCP server entry point. Registers the 14 primitive tools.

This module is a *caller* of the mutation chokepoint, never a bypass of it.
The only tool that changes firewall state is ``opn_plan_apply``, which routes
through ``PlanApplyPipeline.apply()``. There is deliberately no ``opn_api_post``
tool — see ``tests/smoke/test_mcp_server.py``.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any

import yaml
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import ListToolsRequest, ListToolsResult, ServerResult, TextContent, Tool

from opnsense_agent.client.api import OpnApiClient
from opnsense_agent.client.ssh import OpnSshClient, SshAllowlistError
from opnsense_agent.config import Settings, load_settings
from opnsense_agent.plans.engine import OpHandlerRegistry, PlanApplyPipeline
from opnsense_agent.plans.handlers.dhcp import (
    DhcpScopeCreateHandler,
    DhcpStaticAddHandler,
)
from opnsense_agent.plans.handlers.interface import (
    InterfaceAssignHandler,
    InterfaceConfigureHandler,
)
from opnsense_agent.plans.handlers.vlan import VlanCreateHandler
from opnsense_agent.plans.schema import Plan
from opnsense_agent.plans.store import PlanStore
from opnsense_agent.safety.backup import BackupStore
from opnsense_agent.safety.diff import diff_config_xml
from opnsense_agent.safety.lockout import check_plan as lockout_check_plan
from opnsense_agent.safety.probe import reachability_probe

logger = logging.getLogger(__name__)

EXPECTED_TOOLS: list[str] = [
    # Read-only
    "opn_api_get",
    "opn_ssh_exec_readonly",
    "opn_status",
    "opn_get_self_ip",
    # Backup & restore
    "opn_backup_create",
    "opn_backup_list",
    "opn_backup_restore",
    "opn_config_diff",
    # Plan workflow
    "opn_plan_save",
    "opn_plan_load",
    "opn_plan_list",
    "opn_plan_preview",
    "opn_plan_apply",
    # Safety
    "opn_lockout_check",
]

_TOOL_DESCRIPTIONS: dict[str, str] = {
    "opn_api_get": "GET against an OPNsense /api/... path. Read-only.",
    "opn_ssh_exec_readonly": "Run a read-only shell command on the firewall. Allowlisted.",
    "opn_status": "Composite health snapshot of the firewall.",
    "opn_get_self_ip": "Returns the IP your management session originates from.",
    "opn_backup_create": "Pull config.xml and save with a timestamp + optional label.",
    "opn_backup_list": "List saved backups with timestamps and labels.",
    "opn_backup_restore": "Restore a backup. Two-step: requires confirm=true.",
    "opn_config_diff": "Diff two backups, or backup vs. current config. Secret values redacted.",
    "opn_plan_save": "Validate and persist a plan YAML. Returns plan_id.",
    "opn_plan_load": "Load a saved plan by id.",
    "opn_plan_list": "List saved plans with their statuses.",
    "opn_plan_preview": "Resolve a plan to the API/SSH calls it would make. No mutation.",
    "opn_plan_apply": "Execute a plan. The ONLY path for mutations. Requires confirm=true.",
    "opn_lockout_check": "Analyze a plan for lockout risk.",
}


def _build_registry() -> OpHandlerRegistry:
    registry = OpHandlerRegistry()
    registry.register(VlanCreateHandler())
    registry.register(InterfaceAssignHandler())
    registry.register(InterfaceConfigureHandler())
    registry.register(DhcpScopeCreateHandler())
    registry.register(DhcpStaticAddHandler())
    return registry


def build_server(settings: Settings | None = None) -> Server:
    """Build the MCP server with all 14 tools registered.

    Pulled out as a function so smoke tests can introspect tool names
    (via ``list_registered_tools``) without starting stdio.
    """
    settings = settings or load_settings()
    server: Server = Server("opnsense-agent")

    api = OpnApiClient(firewall=settings.firewall, auth=settings.auth)
    ssh = OpnSshClient(firewall=settings.firewall)
    backup_store = BackupStore(
        runs_dir=settings.runtime.runs_dir,
        retention=settings.runtime.backup_retention,
    )
    plan_store = PlanStore(runs_dir=settings.runtime.runs_dir)
    registry = _build_registry()

    # The pipeline calls ``probe(api=...)`` with no timing args, so bind the
    # configured probe window here rather than relying on the function defaults.
    probe = functools.partial(
        reachability_probe,
        max_seconds=settings.runtime.reachability_probe_seconds,
        interval_seconds=settings.runtime.reachability_probe_interval,
    )

    # v1: lockout self_ip/management_if are resolved at integration time
    # (Task 21). Until then the pipeline uses conservative placeholders that
    # the lockout heuristics treat as "unknown management path".
    self_ip = "0.0.0.0"
    management_if = "igb0"

    pipeline = PlanApplyPipeline(
        store=plan_store,
        registry=registry,
        backup=backup_store,
        api=api,
        ssh=ssh,
        probe=probe,
        self_ip=self_ip,
        management_if=management_if,
        allow_lockout_override=settings.safety.allow_lockout_override,
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:  # pyright: ignore[reportUnusedFunction] - registered via decorator
        return [
            Tool(
                name=n,
                description=_TOOL_DESCRIPTIONS[n],
                inputSchema={"type": "object"},
            )
            for n in EXPECTED_TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:  # pyright: ignore[reportUnusedFunction] - registered via decorator
        try:
            result = await _dispatch(
                name,
                arguments,
                api=api,
                ssh=ssh,
                backup=backup_store,
                plan_store=plan_store,
                pipeline=pipeline,
                self_ip=self_ip,
                management_if=management_if,
            )
            return [TextContent(type="text", text=str(result))]
        except SshAllowlistError as e:
            return [TextContent(type="text", text=f"REJECTED: {e}")]
        except Exception as e:  # noqa: BLE001 - surface any tool error as text, never crash the server
            logger.exception("Tool %s failed", name)
            return [TextContent(type="text", text=f"ERROR: {e}")]

    return server


def list_registered_tools(server: Server) -> list[Tool]:
    """Return the tools registered on ``server`` (introspection/test helper).

    The low-level Server stores the ``@server.list_tools()`` handler keyed by
    ``ListToolsRequest``; we invoke it directly so callers get the real
    registered set rather than re-deriving it from ``EXPECTED_TOOLS``.
    """
    handler = server.request_handlers[ListToolsRequest]

    async def _invoke() -> ServerResult:
        return await handler(ListToolsRequest(method="tools/list"))

    result = asyncio.run(_invoke())
    root = result.root
    if not isinstance(root, ListToolsResult):
        raise TypeError(f"expected ListToolsResult, got {type(root).__name__}")
    return list(root.tools)


async def _dispatch(
    name: str,
    args: dict[str, Any],
    *,
    api: OpnApiClient,
    ssh: OpnSshClient,
    backup: BackupStore,
    plan_store: PlanStore,
    pipeline: PlanApplyPipeline,
    self_ip: str,
    management_if: str,
) -> Any:
    if name == "opn_api_get":
        return await api.get(args["path"], params=args.get("params"))

    if name == "opn_ssh_exec_readonly":
        result = await ssh.exec_readonly(args["command"], timeout=args.get("timeout", 15.0))
        return {"stdout": result.stdout, "stderr": result.stderr, "exit": result.exit_code}

    if name == "opn_status":
        info = await api.get("/api/diagnostics/system/system_information")
        return {"reachable": True, "info": info}

    if name == "opn_get_self_ip":
        # The IP we connect from is the one the firewall sees; resolving it
        # fully needs a live session, so v1 defers to opn_status output.
        return {"self_ip": "see opn_status output"}

    if name == "opn_backup_create":
        backup_id = await backup.create(api=api, label=args.get("label"))
        return {"backup_id": backup_id}

    if name == "opn_backup_list":
        return [
            {"id": r.id, "label": r.label, "created": r.created.isoformat()} for r in backup.list()
        ]

    if name == "opn_backup_restore":
        if not args.get("confirm", False):
            return "REJECTED: opn_backup_restore requires confirm=true."
        # A manual restore is a config mutation too: refuse to interleave with
        # (or queue behind) an in-flight plan apply.
        if pipeline.mutation_lock.locked():
            return "REJECTED: an apply or restore is already in progress; retry when it completes."
        async with pipeline.mutation_lock:
            await backup.restore(api=api, backup_id=args["backup_id"])
        return {"status": "restored", "backup_id": args["backup_id"]}

    if name == "opn_config_diff":
        # backup_id_a is the restore TARGET; baseline is backup_id_b or live config.
        # diff(baseline -> target) reads as "what restoring backup_id_a would do".
        target_id = args["backup_id_a"]
        target_xml = backup.read_xml(target_id)
        baseline_id = args.get("backup_id_b")
        if baseline_id:
            baseline_xml = backup.read_xml(baseline_id)
            from_label, to_label = f"backup {baseline_id}", f"backup {target_id}"
        else:
            baseline_xml = await backup.fetch_current_xml(api)
            from_label, to_label = "current", f"backup {target_id}"
        config_diff = diff_config_xml(baseline_xml, target_xml)
        return config_diff.render(from_label=from_label, to_label=to_label)

    if name == "opn_plan_save":
        plan = Plan.model_validate(yaml.safe_load(args["plan_yaml"]))
        return {"plan_id": plan_store.save(plan)}

    if name == "opn_plan_load":
        return plan_store.load(args["plan_id"]).model_dump(mode="json")

    if name == "opn_plan_list":
        return [
            {
                "plan_id": p.plan_id,
                "description": p.description,
                "status": p.status.value,
                "created": p.created.isoformat(),
            }
            for p in plan_store.list()
        ]

    if name == "opn_plan_preview":
        plan = plan_store.load(args["plan_id"])
        return {"plan_id": plan.plan_id, "ops": [op.model_dump() for op in plan.ops]}

    if name == "opn_plan_apply":
        result = await pipeline.apply(
            args["plan_id"],
            confirm=bool(args.get("confirm", False)),
            override_lockout=bool(args.get("override_lockout", False)),
        )
        return {
            "plan_id": result.plan_id,
            "status": result.status.value,
            "backup_id": result.backup_id,
            "rollback_reason": result.rollback_reason,
            "op_results": [r.model_dump() for r in result.op_results],
        }

    if name == "opn_lockout_check":
        plan = plan_store.load(args["plan_id"])
        warnings = lockout_check_plan(
            plan,
            self_ip=args.get("self_ip", self_ip),
            management_if=args.get("management_if", management_if),
        )
        return [
            {"op_index": w.op_index, "op_type": w.op_type, "message": w.message} for w in warnings
        ]

    raise ValueError(f"Unknown tool: {name}")


async def _run_stdio(server: Server) -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    """Entry point for the ``opnsense-agent-mcp`` script (registered in pyproject)."""
    server = build_server()
    asyncio.run(_run_stdio(server))


if __name__ == "__main__":
    main()
