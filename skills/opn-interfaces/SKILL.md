---
name: opn-interfaces
description: Use when creating, assigning, or configuring OPNsense interfaces — covers physical NIC naming, assignment vs configuration, and IPv4/IPv6 setup.
---

# OPNsense Interfaces

## Physical NIC naming on OPNsense (FreeBSD)

- Intel 1G: `igb0`, `igb1`, `em0`, `em1`
- Intel 10G: `ix0`, `ixl0`
- Realtek: `re0`
- Bridges: `bridge0`, `bridge1`
- VLAN children: `<parent>_vlan<tag>` — e.g. `igb1_vlan30`

## Three-step interface setup

1. **Create** the underlying entity if needed (e.g. `vlan.create`).
2. **Assign** the entity as an OPNsense logical interface (`opt1`, `opt2`, etc.). Until assigned, the entity is invisible to firewall rules.
3. **Configure** the assigned interface (IP, subnet, gateway).

The `interface.assign` op handles step 2; `interface.configure` handles step 3.

## IPv4
- `ipv4`: dotted-quad address (the firewall's IP on this interface)
- `ipv4_subnet`: CIDR bits (e.g. 24 for /24)

## IPv6
- `ipv6: track` to track the WAN delegation
- Or a static `2001:db8::1` form

## Pitfalls
- Never `disable` the management interface (the one your API/SSH session arrives on). The lockout check catches this but the warning exists for a reason.
- After assigning a new interface, OPNsense does NOT auto-create allow rules. Phase A (firewall rules) handles that.
