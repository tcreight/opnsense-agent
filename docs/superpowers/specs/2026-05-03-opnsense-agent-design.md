# OPNsense Agent — Design Spec

**Status:** Draft (pending user review)
**Date:** 2026-05-03
**Author:** Tyler Creighton (with Claude)
**Repo (planned):** `git@github.com:tcreight/opnsense-agent.git` (public)

---

## 1. Purpose

Build a Claude Code plugin that gives the user a conversational, plan-then-apply workflow for managing a single OPNsense firewall/router. The plugin scales from network buildout (VLANs/interfaces/DHCP) through VPN, firewall rules, and into background monitoring — without architectural change between phases.

The agent is designed for a single-user homelab: one OPNsense box, one operator, one workstation running Claude Code.

## 2. Non-goals (v1)

- HA / CARP support
- Multi-firewall management
- Web UI or TUI
- Plan editing inside the agent (re-plan instead)
- Auto-rollback based on metrics other than reachability
- Mutation via SSH outside the plan engine
- Autonomous mutation (the optional phase-D daemon **reports**, never **applies**)

## 3. Architecture overview

**Form factor:** Claude Code plugin.
**Runtime:** Python 3.12+ MCP server, invoked by Claude Code.
**Backend:** Hybrid — OPNsense REST API for config mutations; SSH for diagnostics and the few maintenance ops that have no API.

**Three-layer separation:**
1. **MCP server** — small, stable surface of *primitive* tools. Doesn't grow phase-to-phase.
2. **Skills** — markdown knowledge of OPNsense subsystems, loaded on demand.
3. **Slash commands** — user-facing entry points that invoke the planner agent or call diagnostic tools.

**Mutation chokepoint:** every state change passes through `opn_plan_apply`. This is the single guarantee point for backups, lockout checks, and reachability verification.

## 4. Repository layout

```
opnsense-agent/
├── plugin.json                  # Claude Code plugin manifest
├── pyproject.toml               # Python package
├── README.md                    # Setup, security caveats, usage
├── .mcp.json                    # MCP server registration
├── .gitignore                   # Hardened — committed FIRST
├── .pre-commit-config.yaml      # gitleaks + ruff
│
├── commands/                    # Slash commands
│   ├── opn-plan.md
│   ├── opn-apply.md
│   ├── opn-backup.md
│   ├── opn-status.md
│   ├── opn-rollback.md
│   └── opn-diag.md
│
├── skills/                      # On-demand expertise (v1 set)
│   ├── opn-safety/SKILL.md
│   ├── opn-planning/SKILL.md
│   ├── opn-interfaces/SKILL.md
│   ├── opn-vlans/SKILL.md
│   ├── opn-dhcp/SKILL.md
│   └── opn-troubleshooting/SKILL.md
│
├── agents/
│   ├── opn-planner.md           # Plan-drafting subagent
│   └── opn-diag.md              # Read-only diagnostic subagent
│
├── src/opnsense_agent/
│   ├── mcp_server.py            # MCP entry point
│   ├── client/
│   │   ├── api.py               # OPNsense REST API client
│   │   └── ssh.py               # SSH executor
│   ├── plans/
│   │   ├── schema.py            # Pydantic plan model
│   │   ├── store.py             # Save/load/list
│   │   ├── engine.py            # Op handler registry + executor
│   │   └── handlers/            # One module per op type family
│   │       ├── vlan.py
│   │       ├── interface.py
│   │       └── dhcp.py
│   ├── safety/
│   │   ├── backup.py
│   │   └── lockout.py
│   ├── cli.py                   # `opnsense-agent setup`, `doctor`
│   └── config.py
│
├── tests/
│   ├── unit/
│   ├── smoke/
│   ├── integration/             # Opt-in via OPN_AGENT_INTEGRATION_TEST=1
│   ├── fixtures/
│   └── test_no_secrets_in_repo.py
│
├── docs/
│   └── superpowers/specs/       # Design specs (this file)
│
└── runs/                        # Gitignored
    ├── plans/
    ├── backups/
    └── audit.log
```

## 5. MCP server primitives (14 tools)

**Read-only (always safe):**
- `opn_api_get(path, params?)` — raw GET against `/api/...`.
- `opn_ssh_exec_readonly(command, timeout?)` — SSH execution constrained to a read-only command allowlist.
- `opn_status()` — composite health snapshot (API + SSH + gateway + version + uptime + pending changes).
- `opn_get_self_ip()` — IP the management session originates from.

**Backup & restore:**
- `opn_backup_create(label?)` — pull `config.xml`, save with timestamp, return `backup_id`.
- `opn_backup_list()` — list with timestamps and labels.
- `opn_backup_restore(backup_id, confirm=false)` — two-step restore.
- `opn_config_diff(backup_id_a, backup_id_b=None)` — diff two backups, or backup-vs-current.

**Plan workflow (only mutation path):**
- `opn_plan_save(plan_yaml)` — validate + persist, return `plan_id`.
- `opn_plan_load(plan_id)`
- `opn_plan_list()` — with status (`draft | applied | failed | rolled_back`).
- `opn_plan_preview(plan_id)` — resolve to API/SSH calls, return diff. No mutation.
- `opn_plan_apply(plan_id, confirm=false)` — full apply pipeline (lockout check → backup → execute → reachability probe → mark status).

**Safety analysis:**
- `opn_lockout_check(plan_id)` — list of risky operations and reasons.

**Critical invariant:** there is no `opn_api_post` tool. All mutations route through `opn_plan_apply`.

## 6. Skills (v1)

| Skill | Purpose | When loaded |
|---|---|---|
| `opn-safety` | Two-stage commit, lockout reasoning, rollback procedure. | Default for any mutation workflow. |
| `opn-planning` | Plan YAML schema, op catalog, composition patterns. | Whenever a plan is being drafted. |
| `opn-interfaces` | Physical NIC naming, assignment vs. configuration, IPv4/v6 setup, MTU. | Interface-related requests. |
| `opn-vlans` | VLAN tag selection, parent NIC, assign-as-interface gotcha. | VLAN-related requests. |
| `opn-dhcp` | Scope creation, static mappings, options, Kea vs. ISC. | DHCP-related requests. |
| `opn-troubleshooting` | Symptom → diagnostic recipe map. | Symptom descriptions or `/opn-diag`. |

**Skill template:** frontmatter (`name`, `description`), Concepts (only OPNsense-specific bits), Plan ops (catalog with params), Common patterns (worked YAML examples), Pitfalls, References (API endpoints + related skills).

**Phase additions** (sketch only — designed in their own spec when scheduled):
- v2 / Phase C: `opn-vpn-wireguard`, `opn-vpn-openvpn`
- v3 / Phase A: `opn-firewall-rules`, `opn-aliases`, `opn-nat`
- v4 / Phase D: `opn-monitoring-drift`, `opn-monitoring-health`, `opn-package-updates`

## 7. Slash commands

| Command | Behavior |
|---|---|
| `/opn-plan <description>` | Invokes planner subagent, drafts YAML, saves draft, shows preview. Returns `plan_id`. |
| `/opn-apply <plan_id>` | Lockout check, confirmation prompt (must type configured phrase), runs apply pipeline. Reports per-op results. |
| `/opn-status` | One-shot health snapshot. |
| `/opn-backup [label]` | Manual backup. |
| `/opn-rollback <backup_id>` | Two-step restore. |
| `/opn-diag <description>` | Read-only diagnostic mode (no plan, no mutation). |

## 8. Plan format

```yaml
plan_id: 2026-05-03T14-30-22Z-iot-vlan
description: "Stand up VLAN 30 for IoT on igb1 with /24 and DHCP"
created: 2026-05-03T14:30:22Z
status: draft        # draft | applied | failed | rolled_back

target:
  host: opnsense.lan
  api_user: claude-agent

ops:
  - op: vlan.create
    params: { tag: 30, parent_if: igb1, description: "IoT" }
  - op: interface.assign
    params: { vlan_tag: 30, parent_if: igb1, opn_if_name: opt3, enabled: true }
  - op: interface.configure
    params: { opn_if_name: opt3, ipv4: 10.30.0.1, ipv4_subnet: 24, ipv6: track }
  - op: dhcp.scope.create
    params:
      interface: opt3
      range_from: 10.30.0.100
      range_to: 10.30.0.200
      router: 10.30.0.1
      dns: [10.30.0.1]

execution:
  backup_id: null
  applied_at: null
  results: []
  rollback_reason: null
```

**Op handler registry:** each `op:` value maps to a Python handler in `src/opnsense_agent/plans/handlers/`. Adding a new op type = adding a handler module + entry. Schema does not change.

**File handling:** drafts at `0644`. Once `status` flips to `applied | failed | rolled_back`, the file is `chmod 0444` for an immutable audit trail.

## 9. End-to-end workflow

### Mutation path

```
/opn-plan "VLAN 30 for IoT on igb1, /24, DHCP"
  → planner subagent loads opn-safety + opn-planning + opn-vlans + opn-interfaces + opn-dhcp
  → drafts plan YAML
  → opn_plan_save → plan_id
  → opn_plan_preview → human-readable diff
  → "Saved as <plan_id>. Run /opn-apply <plan_id> to commit."

/opn-apply <plan_id>
  → opn_lockout_check (warnings surface, override required if any)
  → confirmation prompt: "Type '<configured phrase>' to apply"
  → opn_plan_apply pipeline:
      1. opn_backup_create("pre-apply-<plan_id>")
      2. Sequential op execution (stop-on-first-failure)
      3. Reachability probe (30s, 3s interval, ≥1 success required)
      4. On all-green: status=applied, return results
      5. On failure or probe failure: opn_backup_restore, status=failed | rolled_back
  → results reported back, audit log appended
```

### Diagnostic path

```
/opn-diag "Why is my IoT VLAN not getting DHCP leases?"
  → diag subagent loads opn-troubleshooting + opn-dhcp + opn-vlans
  → calls opn_api_get + opn_ssh_exec_readonly
  → reports findings + recommended plan ops (does not save)
  → if user wants to fix: separate /opn-plan invocation
```

## 10. Safety guardrails (six layers)

1. **Architectural** — no `opn_api_post` tool; SSH allowlist for read-only; plan files immutable after apply.
2. **Pre-apply checks** — lockout check, mandatory backup-before-apply.
3. **Per-op execution** — sequential, stop-on-first-failure, results recorded.
4. **Post-apply verification** — 30s reachability probe; auto-rollback on failure.
5. **Manual escape** — `/opn-rollback` always available; two-step confirmation.
6. **Audit log** — append-only `runs/audit.log` for every apply/rollback.

**Lockout check refuses or warns on plans that would:**
- Delete/disable a rule allowing traffic from `opn_get_self_ip()`
- Disable the management interface
- Stop or disable SSH or API services
- Change the management interface IP
- Modify aliases referenced by management rules

**Backup retention:** keep last 50 + all labeled backups. Configurable.

## 11. Configuration & secrets

**Config file:** `~/.config/opnsense-agent/config.toml`, mode `0600` (refused if wider). Outside the repo. Never sourced from the working tree.

```toml
[firewall]
host = "opnsense.lan"
api_port = 443
ssh_port = 22
verify_tls = true              # false only for self-signed homelabs
ssh_user = "root"
ssh_key_path = "~/.ssh/opnsense_ed25519"

[auth]
api_key = "..."
api_secret = "..."

[runtime]
runs_dir = "~/projects/opnsense-agent/runs"
backup_retention = 50          # auto-prune older unlabeled backups
reachability_probe_seconds = 30
reachability_probe_interval = 3

[safety]
require_confirm_phrase = "yes apply"   # must be typed verbatim to apply
allow_lockout_override = true          # set false to make lockout warnings hard-fail
```

**Loading precedence:** env vars (`OPN_AGENT_*`) > config.toml > defaults.

**Three-layer secret-leakage prevention:**
1. `.gitignore` (committed first commit, before anything else): `.env`, `.env.*`, `*.key`, `*.pem`, `*_rsa`, `*_ed25519`, `secrets/`, `config.local.*`, `runs/`, `*.backup.xml`.
2. `pre-commit` running `gitleaks` — blocks commits containing secret-shaped strings.
3. `tests/test_no_secrets_in_repo.py` — greps the working tree; CI fails on match.

**Logging hygiene:** the MCP server never logs `api_key` or `api_secret`. Auth headers redacted. Asserted by unit test.

## 12. Setup flow (README walkthrough)

1. `git clone git@github.com:tcreight/opnsense-agent.git`
2. `pip install -e .` (or `uv pip install -e .`)
3. `pre-commit install`
4. Generate API credentials in OPNsense (System → Access → Users → API keys → "+").
5. `opnsense-agent setup` — interactive wizard, writes `~/.config/opnsense-agent/config.toml` at `0600`.
6. `opnsense-agent doctor` — verifies API + SSH reachability, prints version.
7. Register the plugin with Claude Code (local path install).

`doctor` runs:
- Config exists, mode `0600`
- API round-trip (`/api/diagnostics/system/system_information`)
- SSH round-trip (`uname -a`)
- `runs_dir` writable
- `gitleaks` installed (warn if missing)
- Reports OPNsense version, uptime, current `self_ip`

## 13. Phase roadmap

| Phase | Scope | New skills | New op handlers | New commands |
|---|---|---|---|---|
| **v1 — B (network buildout)** | VLANs, interfaces, DHCP, basic gateway/DNS | `opn-safety`, `opn-planning`, `opn-interfaces`, `opn-vlans`, `opn-dhcp`, `opn-troubleshooting` | `vlan.create`, `interface.assign`, `interface.configure`, `dhcp.scope.create`, `dhcp.static.add` | `/opn-plan`, `/opn-apply`, `/opn-status`, `/opn-backup`, `/opn-rollback`, `/opn-diag` |
| **v2 — C (VPN)** | WireGuard first, then OpenVPN | `opn-vpn-wireguard`, `opn-vpn-openvpn` | `wg.peer.add`, `wg.tunnel.create`, `ovpn.client.add` | (none) |
| **v3 — A (firewall rules)** | Rules, aliases, NAT, port forwards | `opn-firewall-rules`, `opn-aliases`, `opn-nat` | `rule.add`, `rule.move`, `alias.create`, `alias.member.add`, `nat.portforward.create` | (none) |
| **v4 — D (monitoring)** | Drift detection, scheduled backups, package update reporting | `opn-monitoring-drift`, `opn-monitoring-health`, `opn-package-updates` | (mostly read-only) | `/opn-drift`, `/opn-update-check` + separate `systemd --user` daemon for unattended reporting |

**Daemon (phase D):** runs every N minutes via `systemd --user` timer. Reads via the same Python client. Writes drift/health reports to a logfile + an Obsidian-readable note at `~/Documents/Lab_and_Office/opnsense-alerts.md`. **Never calls `opn_plan_apply`.**

## 14. Testing strategy

| Tier | Speed | When | Coverage |
|---|---|---|---|
| **Unit** | <5s | Pre-commit + CI | Plan schema validation, op handler logic with mocked client, lockout check, backup path with fake fs, secret-leakage greps. |
| **Smoke / contract** | ~30s | CI | Skill frontmatter parses, plugin manifest valid, MCP server starts and lists tools, command frontmatter valid. |
| **Integration** | minutes | Manual / opt-in (`OPN_AGENT_INTEGRATION_TEST=1`) | Real OPNsense round-trips. Tests refuse to run unless target host matches `OPN_AGENT_INTEGRATION_HOST`. Resources prefixed `test-`, torn down in `finally`. Pre-test backup + on-failure restore. |

**Always-on secret-leakage tests:**
- `test_no_api_key_in_logs` — captures MCP logs, asserts no key fragments.
- `test_no_secrets_in_working_tree` — greps for OPNsense API key shape and SSH private key headers.
- `test_gitignore_covers_required_patterns` — asserts the mandatory deny patterns are present.

**CI (GitHub Actions):**
1. `ruff check`
2. `pyright` (or `mypy --strict`)
3. Unit + smoke tests
4. `gitleaks detect`

Branch protection on `main` requires all checks green before merge (configured after first push).

## 15. Repo creation (deferred to implementation)

When transitioning to implementation:
- Verify `gh auth status`.
- `gh repo create tcreight/opnsense-agent --public --description "..." --source=. --remote=origin --push` after first commit.
- Initial commit ordering: `.gitignore` + `.pre-commit-config.yaml` + `README.md` skeleton with secrets-handling section first. *Then* everything else.
- Confirm SSH remote (`git remote set-url origin git@github.com:tcreight/opnsense-agent.git`).

## 16. Known limitations (documented, not bugs)

- **Single-workstation lockout assumption.** `opn_get_self_ip()` is the connecting workstation. If the user later needs access from a different machine, lockout protection won't know to protect it. Mitigation: document; v2 can add `protected_sources: [...]` config.
- **Reachability probe is best-effort.** A network change that breaks the agent's connectivity but leaves the firewall functional looks like a probe failure and triggers auto-rollback. Fail-safe direction is correct (revert when uncertain).
- **No HA support.** Single-box only.

## 17. Open questions (to resolve during implementation)

- Final SSH library choice: `paramiko` (mature, sync) vs. `asyncssh` (async, fits MCP better). Lean: `asyncssh`.
- Plan store on-disk format: YAML only, or YAML + parallel JSON for diffing? Lean: YAML only, derive JSON if needed.
- Whether to ship a sample `config.xml` fixture for unit tests, or only generate fixtures from a real OPNsense via a documented capture script. Lean: capture script + small committed fixtures.
