---
name: opn-vlans
description: Use when creating or modifying VLANs on OPNsense — covers tag selection, parent NIC choice, and the assign-as-interface gotcha.
---

# OPNsense VLANs

## Tag selection
- Valid range: 2–4094
- Avoid `1` (treated as native/untagged on most hardware)
- Common convention: tag = third octet of the subnet (10.30.0.0/24 → tag 30) — purely cosmetic, useful for memory.

## Parent interface
- The parent must be a physical NIC (or LAGG), not another VLAN.
- The parent does not need to be assigned itself — VLAN children can use an unassigned parent.

## Two-stage workflow
1. `vlan.create` — creates the VLAN child entity (`igb1_vlan30`).
2. `interface.assign` — assigns it as an OPNsense logical interface (`opt3`).

Forgetting step 2 is the #1 trap: the VLAN exists but firewall rules can't reference it.

## Worked example

```yaml
ops:
  - op: vlan.create
    params: { tag: 30, parent_if: igb1, description: "IoT" }
  - op: interface.assign
    params: { vlan_tag: 30, parent_if: igb1, opn_if_name: opt3, enabled: true }
```

## Verification after apply
- `/opn-status` → confirms reconfigure succeeded
- `opn_api_get('/api/interfaces/vlan_settings/searchItem')` → confirms VLAN exists
- `opn_ssh_exec_readonly('ifconfig igb1_vlan30')` → confirms FreeBSD sees it

## API endpoints used
- `POST /api/interfaces/vlan_settings/addItem`
- `POST /api/interfaces/vlan_settings/reconfigure`

## Related skills
- `opn-interfaces` for the assign/configure follow-up
- `opn-dhcp` for adding a DHCP scope to the new interface
