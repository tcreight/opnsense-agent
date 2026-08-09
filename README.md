# OPNsense Agent

A Claude Code plugin for managing a single OPNsense firewall via a plan-then-apply workflow. Uses the OPNsense REST API for config mutations and SSH for diagnostics.

> **Status:** v1 — covers VLANs, interfaces, DHCP. See [roadmap](#roadmap) for future phases.

## ⚠️ Secrets handling

This plugin requires an OPNsense API key/secret and an SSH key. **They are never stored in this repository.**

- Secrets live in `~/.config/opnsense-agent/config.toml` (mode `0600`, refused if wider).
- The repo's `.gitignore` denies `.env`, `*.key`, `*.pem`, `*_rsa`, `*_ed25519`, `secrets/`, `config.local.*`, `apikey.txt`, `runs/`, and config backups.
- A `pre-commit` hook runs `gitleaks` on every commit and blocks anything that looks like a secret.
- A CI test (`tests/test_no_secrets_in_repo.py`) greps the working tree for OPNsense-shaped API keys and SSH private-key headers; CI fails on a match.

If you find a way to commit a secret, that is a bug. File an issue.

## Setup

### 1. Generate OPNsense API credentials

In the OPNsense UI:
- System → Access → Users → (your user) → click "+" under API keys
- Download the resulting `apikey.txt` (contains `key=` and `secret=` lines)

### 2. Set up SSH

OPNsense ships with SSH disabled by default. Enable it under System → Settings → Administration. Add your public key under your user's "authorized keys."

Verify from your workstation:
```bash
ssh -i ~/.ssh/your_opn_key root@<firewall-host> 'uname -a'
```

### 3. Install the plugin

```bash
git clone git@github.com:tcreight/opnsense-agent.git
cd opnsense-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pre-commit install
```

### 4. Run the setup wizard

```bash
opnsense-agent setup
```

This writes `~/.config/opnsense-agent/config.toml` at mode `0600`. Paste your API key/secret when prompted.

### 5. Verify

```bash
opnsense-agent doctor
```

Expected output:
```
✓ Config OK (~/.config/opnsense-agent/config.toml)
✓ API reachable (opnsense.lan)
  Version: 24.7.x
✓ SSH reachable (FreeBSD opnsense.lan ...)
```

### 6. Register with Claude Code

Add to your Claude Code config (typically `~/.claude/config.json` or via `/plugins`):

```json
{
  "plugins": [
    "/home/tylerc/projects/opnsense-agent"
  ]
}
```

Restart Claude Code. The six `/opn-*` slash commands should now appear.

## Usage

### Build a new VLAN end-to-end

```
/opn-plan VLAN 30 for IoT on igb1, /24, DHCP enabled, scope 10.30.0.100-200
```

The planner drafts a plan, saves it, shows you the preview. You'll see something like:

```
Saved as 2026-05-03T14-30-22Z-iot-vlan
Preview:
  - vlan.create: tag=30 parent=igb1 desc="IoT"
  - interface.assign: vlan_tag=30 -> opt3
  - interface.configure: opt3 ip=10.30.0.1/24
  - dhcp.scope.create: opt3 100-200 router=10.30.0.1
Apply with: /opn-apply 2026-05-03T14-30-22Z-iot-vlan
```

### Apply

```
/opn-apply 2026-05-03T14-30-22Z-iot-vlan
```

You'll be asked to type the configured confirmation phrase (default `yes apply`). After confirming:
- Pre-apply backup created
- Each op executes
- Reachability probe runs for 30s
- If anything goes wrong, the backup is restored automatically

### Diagnose without changing anything

```
/opn-diag Why is DHCP not working on opt3?
```

The diag agent investigates read-only. It will tell you what's wrong and recommend a `/opn-plan` to fix it.

### Manual backup / rollback

```
/opn-backup before-gui-work
/opn-rollback 20260503T143022Z-before-gui-work
```

### Status check

```
/opn-status
```

## Roadmap

- v1 — VLANs, interfaces, DHCP, basic gateway/DNS *(this release)*
- v2 — VPN (WireGuard, OpenVPN)
- v3 — Firewall rules, aliases, NAT, port forwards
- v4 — Drift detection + monitoring daemon

## Architecture

See [`docs/superpowers/specs/2026-05-03-opnsense-agent-design.md`](docs/superpowers/specs/2026-05-03-opnsense-agent-design.md).

Quick summary:
- **MCP server** exposes 14 primitive tools (read-only API/SSH, backup/restore, plan workflow, lockout check)
- **Skills** hold OPNsense expertise; load on demand
- **Slash commands** are workflow entry points
- **All mutations route through `opn_plan_apply`** — single chokepoint for backup, lockout check, reachability verification

## Safety guarantees

- No `opn_api_post` tool exists — every mutation has a backup and a verification step
- SSH from the MCP layer is allowlisted to read-only commands
- Plan files become 0444 (immutable) once a plan transitions out of `draft`
- Auto-rollback on op failure or post-apply reachability failure
- Manual `/opn-rollback` always available
- `opn_config_diff` redacts secret values (passwords, PSKs, private keys, API
  secrets, and anything tag-named like one) from its output by default —
  changed secrets show as `[redacted]`, but the changed path is still reported
- `opn_config_diff` parses `config.xml` with the standard-library
  `xml.etree.ElementTree`. This is a deliberate zero-dependency choice: the
  input is our own firewall's config (no DTDs/entities), fetched over
  authenticated TLS or read from a file we wrote. If you ever diff configs from
  an untrusted source, switch to the hardened `defusedxml` package.

See spec section 10 for the full six-layer safety stack.

## Testing

```bash
pytest tests/unit tests/smoke -v          # fast, no firewall
OPN_AGENT_INTEGRATION_TEST=1 OPN_AGENT_INTEGRATION_HOST=opnsense.lan \
  pytest tests/integration -v              # hits real firewall
```

Integration tests refuse to run unless the host matches `OPN_AGENT_INTEGRATION_HOST`.

## License

MIT
