---
name: opn-troubleshooting
description: Use when diagnosing OPNsense issues — symptom → diagnostic recipe map, all read-only.
---

# OPNsense Troubleshooting Recipes

All commands here are read-only (allowlist-safe via `opn_ssh_exec_readonly`).

## "VLAN doesn't show up as a usable interface"
Likely cause: VLAN was created but never assigned.
- `opn_api_get('/api/interfaces/vlan_settings/searchItem')` → confirm it exists
- `opn_api_get('/api/interfaces/overview/...')` → confirm an opt<N> is assigned to it

Fix: a new plan with `interface.assign`.

## "Hosts on new VLAN don't get DHCP leases"
Recipes (in order):
1. `opn_ssh_exec_readonly('ifconfig <opt-name>')` — interface up?
2. `opn_api_get('/api/kea/dhcpv4/get')` — scope present and enabled?
3. `opn_ssh_exec_readonly('tail -n 100 /var/log/dhcpd/latest.log')` — leases attempted?
4. Likely missing: a firewall rule allowing DHCP (UDP 67/68) on the new interface (Phase A territory; manual GUI rule for now).

## "Firewall rule isn't matching"
1. `opn_ssh_exec_readonly('pfctl -sr')` — the rule loaded into pf?
2. `opn_ssh_exec_readonly('pfctl -ss')` — current state table
3. `opn_ssh_exec_readonly('tail -n 200 /var/log/filter/latest.log')` — recent block/pass events

## "Can't reach the firewall after a change"
Stop. Don't issue more changes.
- If `/opn-rollback <backup_id>` fails too → physical/console access required
- The plan that broke things has its `backup_id` recorded — use that ID

## "API returns 401"
- Check `~/.config/opnsense-agent/config.toml` permissions and contents
- API key may have been revoked: System → Access → Users → <user> → API keys
- Run `opnsense-agent doctor`

## Reference
The lockout check exists to prevent the most common self-inflicted outages. If it warned and you overrode the warning, that's the first place to look.
