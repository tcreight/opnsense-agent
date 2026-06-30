# Design: `opn_config_diff` — semantic config.xml diff

**Date:** 2026-06-29
**Status:** Approved, ready for implementation plan
**Closes:** the v1 known gap — `opn_config_diff` is currently a stub at
`src/opnsense_agent/mcp_server.py` that ignores its args and returns
`"config_diff: not yet implemented in v1; track in a follow-up."`

## Problem

The `/opn-rollback` slash command (`commands/opn-rollback.md`, step 2) calls
`opn_config_diff(backup_id_a=<id>)` to show the operator a "brief diff" of
what restoring a backup would change versus the current live config, as a
sanity check **before** the destructive `opn_backup_restore`. Today that call
returns a placeholder, so the rollback flow runs blind. We want a real,
human-readable semantic diff between two OPNsense `config.xml` documents.

Backups are full `config.xml` text snapshots stored at
`runs/backups/<backup_id>.xml`. `BackupStore.create` already fetches the live
config via an API download path. The MCP tool's declared `inputSchema` is just
`{"type": "object"}`, so the parameter contract is convention-only (defined in
`_dispatch` and the command file); no schema migration is required.

## Goals / Non-goals

**Goals**
- Replace the stub with a real semantic diff of two `config.xml` documents.
- Output is advisory and human-readable: it guards a confirmation prompt; it is
  not an authoritative patch/edit-script.
- Zero new runtime dependencies (stdlib only).

**Non-goals**
- Not a general XML patch tool. Reordering of unkeyed positional lists may
  surface as changes; that is acceptable for an advisory diff.
- Not applying or reverting diffs — restore remains `opn_backup_restore`'s job.
- No change to the mutation chokepoint (`PlanApplyPipeline`); diff is read-only.

## Architecture

### New module: `src/opnsense_agent/safety/diff.py` (pure, no I/O)

```
@dataclass(frozen=True)
class Change:
    path: str            # e.g. "vlans/vlan[tag=30]/descr"
    old: str | None      # None for additions
    new: str | None      # None for removals

@dataclass(frozen=True)
class ConfigDiff:
    added: list[Change]      # present in B, absent in A
    removed: list[Change]    # present in A, absent in B
    changed: list[Change]    # leaf text differs between A and B
    @property
    def is_empty(self) -> bool: ...
    def render(self, *, from_label: str = "A", to_label: str = "B") -> str: ...

def diff_config_xml(
    a_xml: str,
    b_xml: str,
    *,
    ignore_paths: frozenset[str] = DEFAULT_IGNORES,
) -> ConfigDiff: ...
```

- Parses both documents with stdlib `xml.etree.ElementTree`.
- **The core is a pure, direction-agnostic A → B diff:** `added`/`removed`/
  `changed` describe what B has relative to A. It bakes in no "backup" /
  "current" / "restore" vocabulary — that framing is the caller's job, supplied
  via `render(from_label=..., to_label=...)`, which only sets the header
  ("Changes from <from_label> to <to_label>:"). `+ path` = present in B (the
  `to` side) only; `- path` = present in A (the `from`) only.
- **Caller responsibility — orient A/B so the diff reads as "what would change
  going from baseline to target."** The rollback flow exploits this: it puts the
  *current* config as A (baseline) and the *backup* as B (target), so the diff
  reads as **"what restoring this backup would do"** (see dispatch wiring).

### Two thin helpers on `BackupStore` (keeps `_dispatch` orchestration-only)

- `read_xml(self, backup_id: str) -> str` — read `runs/backups/<id>.xml`;
  raises `FileNotFoundError` for an unknown id.
- `fetch_current_xml(self, api: OpnApiClient) -> str` — refactor the live-config
  download out of `create()` and reuse it here, so `create()` and the diff path
  share one definition of "the current config XML."

### Dispatch wiring (`mcp_server.py`, `_dispatch`)

`backup_id_a` is always the **restore target** (the snapshot we'd roll back
*to*). The **baseline** we start from is `backup_id_b` if given, else the live
config. The diff runs `baseline → target`, so the result reads as "what
restoring `backup_id_a` would do":

```
if name == "opn_config_diff":
    target_xml = backup.read_xml(args["backup_id_a"])      # restore target
    b_id = args.get("backup_id_b")
    if b_id:
        baseline_xml = backup.read_xml(b_id)               # backup-vs-backup
        from_label, to_label = f"backup {b_id}", f"backup {args['backup_id_a']}"
    else:
        baseline_xml = await backup.fetch_current_xml(api)  # vs live config
        from_label, to_label = "current", f"backup {args['backup_id_a']}"
    diff = diff_config_xml(baseline_xml, target_xml)        # A=baseline, B=target
    return diff.render(from_label=from_label, to_label=to_label)
```

- `backup_id_a` is required — the restore target. In the rollback flow `+`/`-`/
  `~` therefore describe what the restore would add / remove / change relative to
  the current config.
- `backup_id_b` is optional; omitted ⇒ baseline is the live config. Present ⇒
  backup-vs-backup ("what restoring `_a` would do if the system looked like
  `_b`"). Matches the `_a`/`_b` naming the command already uses and is a
  near-free generalization.

## Element matching (the crux of a semantic diff)

Recursive compare of a node's children:

1. **Unique tag on both sides** → match the pair, recurse.
2. **Repeated siblings** (e.g. multiple `<vlan>`): pick a key, in order of
   preference:
   a. the `uuid` attribute, if present (modern OPNsense model sections);
   b. else the text of the first available identifying child from the
      preference list `("tag", "mac", "name", "if", "descr")` — ordered
      STABLE identifiers first, mutable labels last. Keying on a field that
      can change (e.g. `descr`) would make an edit to that field look like a
      remove+add instead of an in-place change, so `descr` is the last resort;
   c. else positional index (documented fallback).
   Match A-children to B-children by key.
3. **Matched pairs recurse.** A leaf whose text differs → a `changed` entry
   `~ path: old -> new`. A child present on only one side → `added`/`removed` of
   the whole subtree.

**Path rendering:** slash-joined element tags, with a `[key]` suffix for keyed
list items, e.g. `vlans/vlan[tag=30]/descr`, `dhcpd/opt3/staticmap[aa:bb:cc]`.

**Ignored noise:** `DEFAULT_IGNORES` drops always-volatile nodes so the diff
shows real config deltas. v1 set: the top-level `revision` block (its `time`,
`seqid`, `description`, `username` always differ between any two snapshots).
The set is a documented module constant, easy to extend.

**Rendered output shape** (rollback case: `from_label="current"`,
`to_label="backup 20260503T143022Z-before-gui-work"`):

```
Changes from current to backup 20260503T143022Z-before-gui-work:
  ~ interfaces/vlan[tag=4090]/tag: 4090 -> 30
  - dhcpd/opt3/staticmap[aa:bb:cc]
  + sysctl/item[net.inet.ip.forwarding]

3 changes across 2 sections
```

Read as "what restoring this backup would do": `~` reverts the VLAN tag, `-`
removes a staticmap that exists now but not in the backup, `+` re-adds a sysctl
the backup had. An empty diff renders a single clear line, e.g.
`No differences (revision metadata ignored).`

## Security note (required in code comments AND README)

We parse `config.xml` with stdlib `xml.etree.ElementTree`. ElementTree is
subject to classic XML entity-expansion attacks (e.g. "billion laughs") and
external-entity resolution on hostile input. This input is **our own
firewall's** config, fetched over an authenticated TLS session and/or read from
a file we wrote ourselves; OPNsense config.xml contains no DTDs or entity
declarations. So stdlib is an accepted, deliberate choice for v1, not an
oversight. The hardened alternative is the `defusedxml` package; revisit if the
trust model ever changes (e.g. diffing configs from an untrusted source).
This rationale is documented at the parse site in `diff.py` and called out in
the README's safety/architecture section.

## Error handling

- Malformed or empty XML on either side → raise `ConfigError` (from
  `config.py`) naming which side failed. `_dispatch`'s existing catch-all
  renders it as `ERROR: ...` text; the server never crashes.
- Unknown `backup_id` → `BackupStore.read_xml` raises `FileNotFoundError`,
  surfaced as text by the same catch-all.
- No `inputSchema`/`EXPECTED_TOOLS` change ⇒ tool count stays 14 ⇒ the
  `test_server_registers_all_expected_tools` smoke test is unaffected.

## Testing

`diff_config_xml` is pure and the primary test target — crafted XML strings:

- identical documents → `is_empty` true, friendly render.
- modified leaf → one `changed` with correct `old -> new`.
- added / removed top-level section.
- repeated siblings keyed by `uuid`: a modify shows as `~` (not add+remove).
- repeated siblings keyed by identifying child (`tag`): add and remove detected.
- the `revision` block differs but is ignored → not reported.
- path rendering includes the `[key]` suffix.

`BackupStore.read_xml` / `fetch_current_xml`: small unit tests (read a written
file; unknown id raises; `fetch_current_xml` matches what `create` would store)
using the existing fake/mocked `OpnApiClient` pattern.

The `/opn-rollback` command file needs no change — its step-2 call starts
working the moment the stub is replaced.

## Files

- Create: `src/opnsense_agent/safety/diff.py`
- Create: `tests/unit/safety/test_diff.py`
- Modify: `src/opnsense_agent/safety/backup.py` (add `read_xml`,
  `fetch_current_xml`; refactor `create` to use the latter)
- Modify: `tests/unit/safety/test_backup.py` (cover the two new helpers)
- Modify: `src/opnsense_agent/mcp_server.py` (implement the `opn_config_diff`
  dispatch branch)
- Modify: `README.md` (ElementTree security callout in safety/architecture)
