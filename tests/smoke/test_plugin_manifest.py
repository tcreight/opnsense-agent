"""Smoke tests: the plugin manifest and MCP registration are well-formed.

These guard the two files Claude Code reads to load the plugin and launch
the MCP server, so a typo here breaks the whole integration silently.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_plugin_manifest_is_valid_json() -> None:
    manifest = json.loads((REPO_ROOT / "plugin.json").read_text())
    assert manifest["name"] == "opnsense-agent"
    assert "version" in manifest
    assert "description" in manifest


def test_mcp_json_registers_server() -> None:
    mcp = json.loads((REPO_ROOT / ".mcp.json").read_text())
    assert "mcpServers" in mcp
    assert "opnsense-agent" in mcp["mcpServers"]
    server_cfg = mcp["mcpServers"]["opnsense-agent"]
    # CLAUDE_PLUGIN_ROOT must be used so the plugin is portable.
    assert "${CLAUDE_PLUGIN_ROOT}" in server_cfg.get("command", "") + " ".join(
        server_cfg.get("args", [])
    )
