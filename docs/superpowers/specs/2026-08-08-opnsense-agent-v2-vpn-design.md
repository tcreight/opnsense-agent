# OPNsense Agent v2 — VPN (WireGuard + OpenVPN) Design Spec

**Status:** Draft (pending user review)
**Date:** 2026-08-08
**Author:** Tyler Creighton (with Claude, Teammate C)
**Depends on:** v1 (`docs/superpowers/specs/2026-05-03-opnsense-agent-design.md`, complete),
`opn_config_diff` (`docs/superpowers/specs/2026-06-29-opn-config-diff-design.md`, complete)
**Blocked by (parallel work, referenced not designed here):** ~~a redaction mechanism for
`opn_config_diff` render output~~ — landed 2026-08-08 (secret-tag redaction at
Change-construction time in `safety/diff.py`); see §11.

---

## 1. Purpose

Extend the v1 plan-then-apply architecture to WireGuard and OpenVPN so the operator can
stand up and manage VPN tunnels the same way they stand up VLANs today: draft a plan,
preview it, apply it through the one chokepoint, get an automatic rollback if it breaks
reachability. v2 introduces **zero new MCP tools** — it grows the op catalog and the
skill/handler set that plug into the existing pipeline.

## 2. Non-goals (v2)

- Certificate Authority or certificate issuance/rotation (System → Trust). Deferred — see
  §3 and Open Question 3.
- Full parity between WireGuard and OpenVPN in one release. §3 recommends WireGuard-first.
- Site-to-site mesh topologies, multi-peer routing policy, or BGP-over-WireGuard.
- Client config export/QR-code generation (`/api/openvpn/export`, WG `wg-quick` file
  rendering) — read-only nice-to-have, not a mutation, punt to a skill doc if wanted later.
- Changes to `PlanApplyPipeline` itself. v2 handlers wire **up** to the existing chokepoint;
  the engine, lockout module *shape*, and backup/restore/probe flow are unchanged code paths
  (their *content* — allowlists, warning rules — does grow, see §10).

## 3. Scope decision: WireGuard vs OpenVPN

**Recommendation: WireGuard gets full CRUD in v2. OpenVPN gets a narrow slice
(server/client instance CRUD, referencing pre-existing certs by `refid`) or trails to
v2.1.** This needs Tyler's sign-off (Open Question 2) but the reasoning:

- WireGuard's secret material is a Curve25519 keypair per side plus an optional
  preshared key — no PKI, no CA, no cert lifecycle. It fits the "one handler = one API
  call, params are a flat dict" pattern v1 already uses for `vlan.create`/`dhcp.*` almost
  unchanged.
- OpenVPN needs a CA, a server cert, and (usually) a client cert per peer before a single
  tunnel op is meaningful. Building CA/cert issuance into v2 would mean the agent holding
  and rotating a **root CA private key** — a much bigger security surface than anything
  v1 shipped, and it deserves its own spec and its own review, not to ride in on VPN
  plumbing. So v2 treats existing certs as an external precondition: the operator creates
  CA + server cert via the OPNsense GUI first (documented in the `opn-vpn-openvpn` skill),
  and OpenVPN op handlers only ever reference them by `refid` — the agent never sees or
  generates private key material for certs.

**In scope (WireGuard):** `wg.instance.create/configure/delete`, `wg.peer.add/update/remove`.
**In scope (OpenVPN, narrower):** `ovpn.server.create/delete` (references existing CA/cert
`refid`), `ovpn.client.add/remove` (peer-style connections, not the CA/cert-generating GUI
wizard flow).
**Deferred:** cert/CA management ops of any kind; OpenVPN static-key (non-TLS) mode; WG
`onboot`/multi-address edge cases beyond a single tunnel address.

## 4. Architecture — extending v1 without new tools

The chokepoint invariant from `engine.py`'s module docstring is unchanged and is the load-
bearing constraint for this whole spec: *"All mutating interactions with the OPNsense
firewall MUST funnel through `PlanApplyPipeline.apply()`."* v2 adds five to nine new
`OpHandler` implementations registered in `_build_registry()` (`mcp_server.py`), the same
way `VlanCreateHandler` etc. are registered today. No new MCP tool, no new dispatch branch
in `_dispatch` beyond what already exists (`opn_plan_save/apply/preview/...` already accept
arbitrary `op:` strings — the schema doesn't enumerate op types, the registry does).

**Why no new tools:** the MCP surface is a stability contract (`EXPECTED_TOOLS`,
`test_server_registers_all_expected_tools`) and the project's stated discipline is "prefer
new op types + skills over new tools." Every VPN action — create a tunnel, add a peer,
check status — is either a mutation (routes through `opn_plan_*`) or a read (already
covered by `opn_api_get` / `opn_ssh_exec_readonly`, whose allowlist gets new entries, not
new tools — see §7).

## 5. Repository layout (delta from v1)

```
src/opnsense_agent/plans/handlers/
├── wireguard.py          # NEW — wg.instance.*, wg.peer.*
└── openvpn.py            # NEW — ovpn.server.*, ovpn.client.*

src/opnsense_agent/safety/
└── lockout.py             # MODIFIED — VPN-aware warning rules (§10.1)

src/opnsense_agent/client/
└── ssh.py                 # MODIFIED — adds a handler-only "trusted exec" path (§7.3)

src/opnsense_agent/plans/
└── store.py                # MODIFIED — sensitive-param file permission tightening (§11)

skills/
├── opn-vpn-wireguard/SKILL.md   # NEW
└── opn-vpn-openvpn/SKILL.md     # NEW

tests/unit/plans/handlers/
├── test_wireguard.py      # NEW
└── test_openvpn.py        # NEW
tests/unit/safety/
└── test_lockout.py         # MODIFIED — VPN warning cases
tests/integration/
├── test_wg_roundtrip.py    # NEW (opt-in)
└── test_ovpn_roundtrip.py  # NEW (opt-in, requires pre-provisioned test cert)
```

No changes to `commands/` are required for v2 to function (see §15 for the one commands
question left open).

## 6. New op types

| Op | Params (draft) | Maps to |
|---|---|---|
| `wg.instance.create` | `name`, `listen_port`, `tunnel_address` (CIDR), `mtu?`, `dns?` | new WG server-side interface |
| `wg.instance.configure` | `instance_ref`, any of the above (partial update) | edit existing instance |
| `wg.instance.delete` | `instance_ref` | remove instance |
| `wg.peer.add` | `instance_ref`, `public_key`, `allowed_ips`, `endpoint?`, `keepalive?`, `description?` | add a peer to an instance |
| `wg.peer.update` | `peer_ref`, partial fields | edit a peer |
| `wg.peer.remove` | `peer_ref` | remove a peer |
| `ovpn.server.create` | `name`, `protocol`, `port`, `ca_refid`, `cert_refid`, `tunnel_network` | new OpenVPN server instance |
| `ovpn.server.delete` | `server_ref` | remove server instance |
| `ovpn.client.add` | `server_ref`, `common_name` or `cert_refid`, `remote_network?` | add a client/peer connection |
| `ovpn.client.remove` | `client_ref` | remove a client connection |

**Note on `wg.peer.add.public_key`:** this is the *peer's* public key only. The peer's
private key is generated on the client device (phone, laptop) and never needs to reach the
agent, the plan file, or config.xml — WireGuard is asymmetric, the server only needs the
far side's public key. This sidesteps most of the peer-secret problem by construction; the
`preshared_key` field (optional, both sides need the same value) is the one true secret in
this op — see §11.

**Interface assignment:** creating a WG or OpenVPN instance produces a new pseudo-interface
(`wireguardN`, `ovpnsN`) that must go through the same `interfaces/settings/setItem` +
`reconfigure` dance VLANs do before firewall rules can reference it. v1's
`InterfaceAssignHandler` hardcodes VLAN device-name derivation
(`f"{parent_if}_vlan{vlan_tag}"` — `src/opnsense_agent/plans/handlers/interface.py` line 20),
so it can't be reused as-is. **Decision: generalize it.** Change `interface.assign`'s params
to accept an explicit `if_device` string instead of deriving one from VLAN params, and have
`vlan.create`, `wg.instance.create`, and `ovpn.server.create` each compute their own device
string and hand it to the *same* handler. One handler, three callers — avoids a
`wg.interface.assign` / `ovpn.interface.assign` op-type fork that would just duplicate
`InterfaceAssignHandler`'s body. This is a small breaking change to an existing op's param
shape; flag it in the implementation plan as a compatibility note (any drafted-but-unapplied
v1 plans using the old `vlan_tag`/`parent_if` params would need re-drafting — acceptable
since plans are short-lived and draft-only plans aren't durable state).

## 7. OPNsense API endpoints (flag: unverified against a live box)

OPNsense's WireGuard and OpenVPN API surfaces have both had structural rewrites across
recent releases (WireGuard plugin restructuring; OpenVPN's move from separate
`servers`/`clients` to a unified `instances` model around 24.1). **Everything below is
best-effort recall, not confirmed against Tyler's actual OPNsense version. Verify all
paths against a live box (or the box's `/api` OpenAPI spec if exposed) before writing a
single handler.**

**WireGuard (module `wireguard`, unverified sub-paths):**
- `POST /api/wireguard/server/addServer` / `setServer/{uuid}` / `delServer/{uuid}` /
  `GET getServer/{uuid}` / `searchServer` — instance CRUD ("server" = instance in the API's
  vocabulary, confusingly not the same as OpenVPN's "server").
- `POST /api/wireguard/client/addClient` / `setClient/{uuid}` / `delClient/{uuid}` /
  `searchClient` — peer CRUD ("client" = peer).
- `POST /api/wireguard/service/reconfigure` / `start` / `stop`.
- `GET /api/wireguard/service/showhandshake` (or a `/api/diagnostics/...` sibling) — last
  handshake timestamp per peer, needed for §12 verification. **Path shape most likely to
  have moved between versions — verify first.**

**OpenVPN (module `openvpn`, unverified sub-paths):**
- Unified instances model (24.1+): `POST /api/openvpn/instances/add` / `set/{uuid}` /
  `del/{uuid}` / `toggle/{uuid}` / `GET search`.
- Pre-24.1 (if Tyler's box predates the rewrite): separate `servers`/`clients` endpoints
  with a different body shape entirely. **This is a hard fork in implementation — confirm
  Tyler's OPNsense version before writing `openvpn.py` handlers.**
- `POST /api/openvpn/service/reconfigure` / `start/{uuid}` / `stop/{uuid}`.
- `GET /api/openvpn/service/searchSessions` — connected-client status, needed for §12.
- Cert/CA **lookup only** (read-only, used to resolve `refid` for `ovpn.server.create`):
  `GET /api/trust/cert/search`, `GET /api/trust/ca/search`.

## 8. Secret generation for WireGuard instance keys

The WG *instance's* private key is a true secret that must exist in config.xml (unlike a
peer's). Two ways to produce it, both worth weighing (Open Question 4):

1. **SSH-side `wg genkey`/`wg pubkey` on the firewall itself.** Zero new Python
   dependencies — the `wg` binary already exists on any box running the plugin. Requires a
   new capability: `OpnSshClient` currently exposes only `exec_readonly`, gated by the
   allowlist in `ssh.py` (`_ALLOWLIST`), because that method is reachable from the
   `opn_ssh_exec_readonly` MCP tool — i.e. from strings an LLM tool call supplies. A
   handler-internal SSH call is different: the command string is hardcoded in our own
   handler code, never LLM- or user-supplied, so the allowlist's threat model doesn't
   apply to it. Add `OpnSshClient.exec_trusted(command: str) -> SshResult` — no allowlist
   check, **not exposed through any MCP tool**, callable only from `OpHandler.execute()`
   bodies via `ctx.ssh`. The private key never has to leave the SSH session or transit the
   plan YAML: the handler runs `wg genkey`, captures only the derived public key back into
   `OpResult.response` for confirmation, and feeds the private key straight into the
   `addServer` API call in the same handler invocation.
2. **Generate in-process** with a Python crypto library (e.g. `cryptography`'s
   `X25519PrivateKey`). Simpler data flow, but adds a new runtime dependency not currently
   in `pyproject.toml`, and the key now transits Python process memory and whatever the
   handler passes to `ctx.api.post()` — no worse than option 1's API leg, but doesn't save
   anything and adds a dependency.

**Recommendation: option 1.** It reuses the "SSH for things with no clean API" precedent
from v1 §3 and adds no dependency, at the cost of a new (small, well-scoped) capability on
`OpnSshClient`. Flagged as Open Question 4 because it's the one place this spec proposes
genuinely new client-layer capability rather than just a new handler.

## 9. Plan schema impact

None. `PlanOp.params: dict[str, Any]` (`schema.py` line 23) already accepts arbitrary keys —
same pattern v1 used for `dhcp.scope.create`'s `dns: [10.30.0.1]` list param. No Pydantic
model changes needed; op-shape validation stays inside each handler (`KeyError` on a missing
required param surfaces as an `OpResult(status="error")`, same as today).

Example plan for a home-to-phone WireGuard tunnel:

```yaml
plan_id: 2026-08-08T10-00-00Z-wg-remote-admin
description: "WireGuard tunnel for remote admin access from phone"
ops:
  - op: wg.instance.create
    params: { name: wg0, listen_port: 51820, tunnel_address: 10.90.0.1/24 }
  - op: interface.assign
    params: { if_device: wireguard0, opn_if_name: opt5, enabled: true }
  - op: wg.peer.add
    params:
      instance_ref: wg0
      public_key: "<pasted from phone's WireGuard app>"
      allowed_ips: ["10.90.0.2/32"]
      description: "tyler-phone"
```

Note `if_device: wireguard0` — the generalized `interface.assign` from §6, not a new op.

## 10. Safety guardrails — extended stack

v1's six-layer stack (architectural / pre-apply / per-op / post-apply / manual escape /
audit log) is unchanged in *shape*. v2 extends layers 2 and 4 with VPN-aware content.

### 10.1 Lockout check extensions (layer 2)

`lockout.py`'s `_check_op` gets new branches, same style as the existing
`interface.configure`/`service.disable`/`rule.delete` rules:

- `wg.instance.delete` / `wg.instance.configure` (port/address change) / `wg.peer.remove` /
  `wg.peer.update` (allowed_ips/key change) → warn if the target instance/peer matches the
  **currently connected management session's** path (see 10.2 for how that's determined).
- `ovpn.server.delete` / `ovpn.client.remove` → same pattern.
- `service.disable` with `name in {"wireguard", "openvpn"}` → added to `_DANGEROUS_SERVICES`.

### 10.2 VPN-path management lockout (the v2-specific hazard)

**The hazard:** if the operator manages the firewall *over* a WireGuard or OpenVPN tunnel
(the classic "I'm at work, my homelab is at home" case), a bad change to that same tunnel
can sever the only path back — and the pipeline's post-apply reachability probe may not
catch it. `reachability_probe()` (`safety/probe.py`) just calls `api.get()` against
`/api/diagnostics/system/system_information` and checks for *any* successful response. If
the operator's machine has another route to the firewall's API (LAN, different VPN, a
still-open SSH session on a separate path) that route can mask total VPN breakage — the
probe reports success while the actual client that depends on the tunnel is now locked out.
This is a genuinely different failure mode than v1's "management interface IP change,"
because the probe runs from the *agent's* vantage point (wherever the MCP server's own
network path to the firewall is), not from the *remote operator's* vantage point.

**Design requirement, two parts:**

1. **Detection.** Before applying a plan that touches a `wg.*`/`ovpn.*` op, resolve whether
   `self_ip` (today a placeholder — see the prerequisite note below) falls inside any
   existing VPN instance's tunnel subnet. If it does, that instance is added to the set of
   "protected management paths" for this apply, alongside the configured `management_if`,
   for the duration of `_check_op`'s pass over this plan.
2. **Fail-closed acknowledgment, not full closed-loop proof.** A fully automatic guarantee
   that the probe specifically re-validated the VPN path (not an incidental LAN path) would
   need either SSH-side introspection of the API's active TCP peer, or an out-of-band
   confirmation channel — both bigger builds than this spec should scope in. Instead: when
   10.1's detection fires, `check_plan` returns a **hard** warning (not a soft one) that
   `LockoutCheckFailedError` surfaces before any apply, same override mechanism as today
   (`override_lockout=True` + `allow_lockout_override` in safety config), but the
   `opn-safety` skill and `/opn-apply` command must tell the operator explicitly: *"This
   plan modifies the VPN path you appear to be connected through. If this change is wrong,
   you may lose remote access with no automatic recovery — keep console/LAN access
   available before proceeding."* This mirrors v1 §16's honest framing of the reachability
   probe as best-effort, fail-safe-by-reverting-when-uncertain, rather than overclaiming a
   guarantee the architecture can't fully back.

**Prerequisite this section depends on:** per the progress notes carried over from v1,
`self_ip` and `management_if` are wired into `PlanApplyPipeline` as **placeholders**
(`"0.0.0.0"` / `"igb0"` in `mcp_server.py`'s `build_server()`) pending real resolution —
tracked historically as "Task 21" work. VPN-aware lockout in 10.1/10.2 is meaningless
against a placeholder `self_ip`. **This needs to be confirmed resolved (or pulled forward
as a v2 blocker) before implementation — Open Question 1.**

## 11. Secrets handling

Three places VPN secrets can leak, and what v2 owns vs. defers:

**What's a secret:** WG instance private key (see §8 — designed to never leave the SSH
session), WG peer preshared key (`wg.peer.add.params.preshared_key` — this one *does* need
to reach the operator, since they must paste it into the client config, so it can't be fully
hidden the way the private key can), OpenVPN's `tls-crypt`/`tls-auth` static key if
generated as part of `ovpn.server.create`.

**Plan files (`runs/plans/*.yaml`):** v1 writes drafts `0644`, finalized plans `0444` —
world/group-readable within the local filesystem's trust boundary. That's a bigger deal once
a plan's `params` can contain a preshared key or static key in cleartext. **New requirement:**
`PlanStore` gets a small `SENSITIVE_PARAM_KEYS` set (module constant, same pattern as
lockout's `_DANGEROUS_SERVICES`) — `{"preshared_key", "tls_crypt_key", "private_key"}` — and
if any op's params contain one of those keys, the plan file is written `0600` instead of
`0644`/`0444`, both at draft time and at finalize time.

**Audit log (`runs/audit.log`):** already safe by omission — `_append_audit` in `engine.py`
logs `plan_id`/`backup_id`/`status`/`rollback_reason` only, never `op.params`. v2 must
preserve this; add an explicit unit test asserting no handler's exception-path
`logger.exception`/`logger.error` call ever interpolates a raw `params` dict (the existing
handlers already avoid this by convention — v2 makes it a tested invariant, not just a
convention, since a WG/OVPN handler's natural debugging instinct is to log the failing body).

**Diff output (`opn_config_diff`):** out of scope to design here — a redaction mechanism for
`ConfigDiff.render()` output is being built in parallel (see spec header). What v2 *does*
own: naming which config.xml paths its new ops introduce that need to land on that
mechanism's block-list — `wireguard/server/*/privatekey`, `wireguard/client/*/presharedkey`,
`openvpn/*/tls`, `openvpn/*/*key*`. Worth flagging to whoever owns the redaction work: this
gap already exists today for any OpenVPN/cert config a user set up by hand through the GUI
before the agent ever touched VPN — `opn_config_diff` renders `Change.old`/`Change.new` as
literal leaf text with no filtering, so a diff spanning an existing OpenVPN section already
prints key material verbatim. It isn't a v2-only problem; v2 just makes it likely to come up
more often. As a low-cost interim seam (not a redaction implementation): consider giving
`ConfigDiff.render()` an optional `redactor: Callable[[str, str], str] | None = None`
parameter now, defaulting to `None` (today's behavior, unchanged), so the parallel work has
a clean place to plug in without renegotiating `diff.py`'s signature later — flagged as Open
Question 6 rather than decided here, since it's arguably that other work's call to make.

## 12. Verification after apply

The pipeline's existing reachability probe (§10.2 caveats aside) is unchanged and still
runs. VPN ops add **op-level** post-checks, distinct from the pipeline-level probe:

- **Instance up, not "peer connected."** After `wg.instance.create`/`ovpn.server.create`,
  verify the API accepted the config (`result == "saved"`, already how every v1 handler
  checks) *and* that `reconfigure` succeeded *and* that the resulting interface reports up
  (`ifconfig <if_device>` via the read-only SSH allowlist, or the API's interface status
  endpoint). **Do not** gate success on a peer handshake having happened — a freshly added
  peer has no reason to have connected yet (the human hasn't opened their WireGuard app),
  so treating "no handshake within N seconds" as a failure would cause the pipeline to
  auto-rollback a perfectly correct peer-add. Handshake/connection status belongs in a
  *diagnostic* check (`/opn-diag` or an `opn_status` VPN section), run on demand after the
  operator actually connects — not a hard gate inside `apply()`.
- **Route presence** for tunnels with routed subnets (WG `allowed_ips` covering a remote
  LAN, or an OpenVPN routed client): confirm the route appears via
  `opn_ssh_exec_readonly("netstat -rn")` — reuses the existing tool and allowlist pattern,
  add `wg`/`ovpnctl`... show-style commands to `_ALLOWLIST` in `ssh.py` for diagnostics
  (e.g. `wg show <if>` with an argument pattern restricting to a known interface-name
  shape, mirroring how `ifconfig`'s pattern already restricts to an interface-name shape).

## 13. Rollback behavior

Unchanged mechanism — this is a deliberate non-change and worth calling out as validation
that v1's chokepoint design anticipated exactly this kind of extension: any op failure or
probe failure triggers the same `_safe_restore` → full `config.xml` restore →
`PlanStatus.failed`/`rolled_back` path that VLAN ops use today. No VPN-specific rollback
logic is needed at the engine level; the risk v2 adds is entirely in §10.2 (the probe
possibly not detecting the specific failure mode), not in the restore mechanism itself.

## 14. Skills (new)

| Skill | Purpose | When loaded |
|---|---|---|
| `opn-vpn-wireguard` | Instance/peer op catalog, key-handling rules (peer pubkey only, never request a private key from the operator), allowed_ips patterns for remote-access vs. site-to-site. | WireGuard-related requests. |
| `opn-vpn-openvpn` | Server/client op catalog, the "certs must already exist" precondition and how to check for one via `opn_api_get` against the trust search endpoints, protocol/port conventions. | OpenVPN-related requests. |

Both skills must explicitly document the VPN-path lockout hazard (§10.2) in their own words,
not just rely on `opn-safety` — the planner subagent loads skills contextually and a VPN
request should surface this warning even if `opn-safety` isn't independently invoked.

## 15. Slash commands

**No new commands required.** `/opn-plan`, `/opn-apply`, `/opn-diag`, `/opn-status` cover
the VPN workflow the same way they cover VLANs — draft, preview, apply, diagnose. The
roadmap table in the v1 spec (§13) lists "(none)" for v2 commands; this draft agrees, with
one open question: should `/opn-status`'s composite snapshot gain a VPN section (interface
up/down + last-handshake age per instance), or is that better left to `/opn-diag`
on-demand? See Open Question 7 — leaning toward extending `/opn-status` since "is my tunnel
up" is exactly the kind of one-shot health question that command already answers for the
rest of the box, but it does mean an extra `opn_api_get` call or two inside that command's
existing procedure, not a new tool.

## 16. Testing strategy

| Tier | New coverage |
|---|---|
| **Unit** | `test_wireguard.py`/`test_openvpn.py`: handler request-body shape + error-path tests, mirroring `tests/unit/plans/handlers/test_dhcp.py`'s mocked-`OpnApiClient` pattern. `test_lockout.py`: new VPN warning cases (instance delete while `self_ip` in tunnel subnet; peer remove; service.disable for wireguard/openvpn). New: plan-file-permission test (`0600` when a sensitive param key is present). New: a grep-style test (alongside `test_no_secrets_in_repo.py`'s pattern) asserting no VPN handler's exception log line formats a raw `params` dict. |
| **Smoke** | `test_server_registers_all_expected_tools` needs **no change** — that's the point; add a companion assertion that `OpHandlerRegistry.known_types()` grew to include the new `wg.*`/`ovpn.*` ops without the tool list changing, so a future regression that accidentally adds a tool instead of an op type is caught explicitly. New skill frontmatter parses for the two new skill dirs. |
| **Integration** | (opt-in, `OPN_AGENT_INTEGRATION_TEST=1`, same guardrails as v1: resources prefixed `test-`, torn down in `finally`, pre-test backup + on-failure restore.) `test_wg_roundtrip.py`: create instance + peer, verify via API, delete. Self-contained — no external precondition. `test_ovpn_roundtrip.py`: **requires a pre-provisioned test CA/cert on the target box** (documented manual one-time setup, since cert issuance is out of scope for the agent itself) — more fragile than the WG test because of that external dependency; gate it behind a second env var naming the test cert `refid` so it skips cleanly (not just fails) on boxes without that fixture. |

## 17. Known limitations (v2, documented not fixed)

- **VPN-path lockout is a warning, not a guarantee** (§10.2) — the probe can't distinguish
  "firewall reachable via LAN" from "firewall reachable via the specific VPN path the
  operator depends on." Mitigation is operator discipline (keep an out-of-band path open)
  plus a loud warning, same fail-safe philosophy as v1 §16's reachability-probe caveat.
- **OpenVPN is inert without pre-existing certs.** v2's `ovpn.*` ops do nothing useful on a
  box with no CA/cert already provisioned through the GUI. If Open Question 3 resolves to
  "defer OpenVPN entirely," this whole surface waits for v3.
- **`interface.assign`'s param-shape change (§6) is a breaking change** to an existing v1 op,
  not additive. Any drafted-but-unapplied plan from before this change needs re-drafting.

## 18. Open questions for Tyler

1. **`self_ip`/`management_if` resolution** — the progress notes describe these as
   placeholders pending real wiring (historically "Task 21"). Has that shipped since? If
   not, it blocks §10.2's VPN lockout logic from doing anything meaningful and should be
   pulled forward as a hard prerequisite for v2, not done inline with VPN work.
2. **OpenVPN parity** — ship WireGuard-only in v2 and trail OpenVPN to v2.1/v3 (this
   draft's lean), or build both together now? PKI complexity is the argument for trailing.
3. **Cert/CA management scope** — confirm agreement that it's fully deferred (agent
   references existing certs by `refid` only, never issues/rotates them). This effectively
   caps how useful `ovpn.*` ops are on their own — worth confirming that's acceptable before
   committing engineering time to them.
4. **WG instance-key generation mechanism** (§8) — SSH-side `wg genkey` via a new
   handler-only "trusted exec" capability on `OpnSshClient` (recommended: no new deps, small
   new capability), vs. in-process generation with a new `cryptography` dependency, vs.
   requiring the operator to supply the key themselves (simplest, but reintroduces a private
   key transiting the plan file that §8's design tries to avoid).
5. **Live-box endpoint verification** — §7's endpoint list is unverified recall, and
   OpenVPN's API shape is a hard version fork (pre/post the unified-instances rewrite). Need
   Tyler's actual OPNsense version before an implementation plan can commit to real paths.
6. **Diff redaction seam** — RESOLVED 2026-08-08: the parallel redaction work landed at
   Change-construction time inside the diff walk (`safety/diff.py` `_SECRET_TAGS` /
   `_SECRET_TAG_SUFFIXES`), deeper than a `render()` seam, so no `redactor` parameter is
   needed. The config paths §11 names are covered by that tag set (`privatekey` suffix,
   `presharedkey` / `tls` exact matches).
7. **`/opn-status` VPN section** — extend the existing composite health snapshot with
   interface-up/last-handshake info (§15), or leave that to `/opn-diag` on demand and keep
   `/opn-status` unchanged? Either is consistent with "no new commands."
8. **Plan-file permission tightening** (§11) — `0600` for any plan containing a sensitive
   param key is a v1 behavior change (today all plan files are `0644`/`0444` regardless of
   content). Confirm this is desired before it ships as a cross-cutting `PlanStore` change.
