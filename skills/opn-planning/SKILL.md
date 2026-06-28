---
name: opn-planning
description: Use when drafting an OPNsense plan YAML — covers schema, op catalog, and composition patterns.
---

# Plan YAML Schema

```yaml
plan_id: <ISO-8601 timestamp>-<short-slug>
description: <one line>
created: <ISO-8601 UTC timestamp>
status: draft     # set by engine, do not change manually
target:
  host: <hostname or IP>
  api_user: <optional, for audit>
ops:
  - op: <op.type>
    params: { ... }
execution:        # filled by engine; leave empty in drafts
  backup_id: null
  applied_at: null
  results: []
  rollback_reason: null
```

## v1 op catalog

### `vlan.create`
- `tag` (int, 2-4094, avoid 1)
- `parent_if` (str, e.g. `igb1`)
- `description` (str)

### `interface.assign`
- `vlan_tag` (int)
- `parent_if` (str)
- `opn_if_name` (str, e.g. `opt3`)
- `enabled` (bool, default true)

### `interface.configure`
- `opn_if_name` (str)
- `ipv4` (str, IP address)
- `ipv4_subnet` (int, CIDR bits)
- `ipv6` (str, optional)

### `dhcp.scope.create`
- `interface` (str)
- `subnet` (str, CIDR)
- `range_from`, `range_to` (str)
- `router` (str)
- `dns` (list[str])

### `dhcp.static.add`
- `interface` (str)
- `mac` (str)
- `ip` (str)
- `hostname` (str, optional)

## Composition patterns

### Stand up a new VLAN-based subnet end-to-end
```yaml
ops:
  - op: vlan.create
    params: { tag: 30, parent_if: igb1, description: "IoT" }
  - op: interface.assign
    params: { vlan_tag: 30, parent_if: igb1, opn_if_name: opt3, enabled: true }
  - op: interface.configure
    params: { opn_if_name: opt3, ipv4: 10.30.0.1, ipv4_subnet: 24 }
  - op: dhcp.scope.create
    params:
      interface: opt3
      subnet: 10.30.0.0/24
      range_from: 10.30.0.100
      range_to: 10.30.0.200
      router: 10.30.0.1
      dns: [10.30.0.1]
```

Order matters: VLAN before assignment before configuration before DHCP.

## Pitfalls
- Do not skip `interface.assign` after `vlan.create` — the VLAN won't be usable as a routed interface otherwise.
- Use `opt<N>` names consistent with what's already taken; check via `opn_api_get('/api/interfaces/overview/...')` first.
- Avoid VLAN tag 1 (default/native).
