---
name: opn-dhcp
description: Use when creating DHCP scopes or static reservations on OPNsense — covers Kea (default in 24+) workflow and gotchas.
---

# OPNsense DHCP (Kea)

## Backend
OPNsense 24+ uses **Kea** by default for new installs. Older installs may still use **ISC** (`/api/dhcpv4/...`). v1 of this plugin targets Kea only.

## Scope creation prerequisites
- The interface (`opt3`, etc.) must already be assigned and configured with an IP.
- The interface IP should be in the same subnet as the scope (and is usually used as the router).

## `dhcp.scope.create` params
- `interface`: OPNsense logical interface name (`opt3`)
- `subnet`: CIDR string (`10.30.0.0/24`)
- `range_from`, `range_to`: pool boundaries
- `router`: gateway IP (usually the interface IP)
- `dns`: list of DNS server IPs

## `dhcp.static.add` params (reservations)
- `interface`: scope's interface
- `mac`: 6-octet MAC, colon-separated
- `ip`: must be inside the subnet, ideally outside the dynamic pool
- `hostname`: optional but recommended

## Worked example

```yaml
ops:
  - op: dhcp.scope.create
    params:
      interface: opt3
      subnet: 10.30.0.0/24
      range_from: 10.30.0.100
      range_to: 10.30.0.200
      router: 10.30.0.1
      dns: [10.30.0.1]
  - op: dhcp.static.add
    params:
      interface: opt3
      mac: aa:bb:cc:dd:ee:ff
      ip: 10.30.0.50
      hostname: thermostat
```

## Pitfalls
- Don't put a static reservation IP inside the dynamic range — Kea will accept it but you'll get conflicts.
- Reconfigure runs after every scope/reservation change. If you're doing many changes, batch them in one plan.

## API endpoints used
- `POST /api/kea/dhcpv4/addSubnet`
- `POST /api/kea/dhcpv4/addReservation`
- `POST /api/kea/service/reconfigure`
