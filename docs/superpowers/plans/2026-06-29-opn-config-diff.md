# opn_config_diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `opn_config_diff` stub with a real semantic diff between two OPNsense `config.xml` documents, so `/opn-rollback` can show "what restore would do" before a destructive restore.

**Architecture:** A pure, direction-agnostic diff core (`safety/diff.py`, stdlib `xml.etree.ElementTree`) compares two config XML strings into a `ConfigDiff` of added/removed/changed entries with a `render()` method. `BackupStore` gains `read_xml`/`fetch_current_xml` helpers so the MCP `_dispatch` branch stays orchestration-only. The rollback flow orients A=baseline (current/another backup), B=target (the backup to restore), so the rendered diff reads as the changes a restore would apply.

**Tech Stack:** Python 3.12, stdlib only (no new deps), pytest (asyncio_mode=auto), pyright strict, ruff.

**Spec:** `docs/superpowers/specs/2026-06-29-opn-config-diff-design.md`

## Global Constraints

- **Python 3.12, stdlib only** — no new runtime dependencies. XML parsing uses `xml.etree.ElementTree`.
- **pyright strict** runs on `src` AND `tests`. Annotate every function param and return. Do NOT rely on `# type: ignore[<mypy-code>]` — pyright ignores mypy codes and the `Unknown` cascades.
- **Pydantic/dataclass list fields:** use `field(default_factory=list[Change])` (subscripted), not `default_factory=list`, or pyright strict flags `list[Unknown]`.
- **ruff** select = E,F,I,N,UP,B,A,C4,T20,RET,SIM; line-length 100. Exception class names must end in `Error` (reuse existing `ConfigError`).
- **Tests run via `.venv/bin/pytest`** (pytest is not on PATH). asyncio_mode=auto ⇒ write `async def test_...` with NO `@pytest.mark.asyncio`.
- **Diff direction is caller-oriented:** `diff_config_xml(a, b)` reports what B has relative to A. The rollback dispatch passes A=baseline, B=restore-target.
- **Commits go straight to `main`** (established pattern). Footer on every commit:
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_015gSp5YPYDcuPRh2XJqYrfp
  ```
- **`git push` needs the sandbox disabled** (sandbox has no DNS).
- **After code changes, run `graphify update .`** to keep the graph current.

---

### Task 1: BackupStore — `fetch_current_xml` + `read_xml`, refactor `create`

**Files:**
- Modify: `src/opnsense_agent/safety/backup.py`
- Test: `tests/unit/safety/test_backup.py`

**Interfaces:**
- Consumes: existing `BackupStore.__init__(runs_dir, retention)`, module constant `DOWNLOAD_PATH`, `OpnApiClient.get`.
- Produces:
  - `BackupStore.fetch_current_xml(self, api: OpnApiClient) -> str` — pulls the live `config.xml` text.
  - `BackupStore.read_xml(self, backup_id: str) -> str` — reads `runs/backups/<backup_id>.xml`; raises `FileNotFoundError` for an unknown id.
  - `BackupStore.create` unchanged externally (still `-> str`), now delegates its config pull to `fetch_current_xml`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/safety/test_backup.py`:

```python
async def test_fetch_current_xml_returns_config_text(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<opnsense><a/></opnsense>"
    xml = await store.fetch_current_xml(api=fake_api)
    assert xml == "<opnsense><a/></opnsense>"


async def test_read_xml_round_trips_a_created_backup(store: BackupStore) -> None:
    fake_api = AsyncMock()
    fake_api.get.return_value = "<opnsense><b>1</b></opnsense>"
    backup_id = await store.create(api=fake_api)
    assert store.read_xml(backup_id) == "<opnsense><b>1</b></opnsense>"


def test_read_xml_unknown_id_raises(store: BackupStore) -> None:
    with pytest.raises(FileNotFoundError):
        store.read_xml("does-not-exist")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/safety/test_backup.py -v`
Expected: the 3 new tests FAIL with `AttributeError: ... fetch_current_xml` / `read_xml`.

- [ ] **Step 3: Implement the helpers and refactor `create`**

In `src/opnsense_agent/safety/backup.py`, replace the body of `create` and add the two helpers (the `create` config-pull logic moves verbatim into `fetch_current_xml`):

```python
    async def fetch_current_xml(self, api: OpnApiClient) -> str:
        """Pull the live config.xml as text. Shared by create() and config diffs."""
        raw: Any = await api.get(DOWNLOAD_PATH)  # type: ignore[arg-type]
        return raw if isinstance(raw, str) else raw.get("data", "")

    async def create(self, api: OpnApiClient, label: str | None = None) -> str:
        xml_text = await self.fetch_current_xml(api)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        suffix = f"-{label}" if label else ""
        backup_id = f"{ts}{suffix}"
        path = self.runs_dir / "backups" / f"{backup_id}.xml"
        path.write_text(xml_text)
        logger.info("Backup created: %s", backup_id)
        return backup_id

    def read_xml(self, backup_id: str) -> str:
        """Read a stored backup's config.xml. Raises FileNotFoundError if absent."""
        path = self.runs_dir / "backups" / f"{backup_id}.xml"
        if not path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_id}")
        return path.read_text()
```

(`Any` is already imported; `OpnApiClient` is already imported under `TYPE_CHECKING` and used only as an annotation, which `from __future__ import annotations` keeps string-only at runtime.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/safety/test_backup.py -v`
Expected: all tests PASS (the 3 new + the 4 existing).

- [ ] **Step 5: Lint + type check**

Run: `.venv/bin/ruff check src/opnsense_agent/safety/backup.py tests/unit/safety/test_backup.py && .venv/bin/pyright --pythonpath .venv/bin/python src/opnsense_agent/safety/backup.py`
Expected: ruff clean; pyright `0 errors`.

- [ ] **Step 6: Commit**

```bash
git add src/opnsense_agent/safety/backup.py tests/unit/safety/test_backup.py
git commit -m "$(cat <<'EOF'
feat: BackupStore.read_xml + fetch_current_xml helpers

Refactor create() to pull live config via fetch_current_xml so the
same definition of "current config.xml" feeds both backups and the
upcoming opn_config_diff. read_xml loads a stored backup by id.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015gSp5YPYDcuPRh2XJqYrfp
EOF
)"
```

---

### Task 2: Semantic diff core (`diff.py`) with positional keying

**Files:**
- Create: `src/opnsense_agent/safety/diff.py`
- Test: `tests/unit/safety/test_diff.py`

**Interfaces:**
- Consumes: `opnsense_agent.config.ConfigError`.
- Produces:
  - `Change(path: str, old: str | None, new: str | None)` (frozen dataclass).
  - `ConfigDiff(added: list[Change], removed: list[Change], changed: list[Change])` with `is_empty: bool` property and `render(self, *, from_label: str = "A", to_label: str = "B") -> str`.
  - `diff_config_xml(a_xml: str, b_xml: str, *, ignore_paths: frozenset[str] = DEFAULT_IGNORES) -> ConfigDiff`.
  - `DEFAULT_IGNORES: frozenset[str]` (= `{"revision"}`).
  - Module-private `_identity(child, idx) -> str` (Task 3 upgrades this to uuid/identifying-child keying; in Task 2 it is positional `#idx`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/safety/test_diff.py`:

```python
from __future__ import annotations

import pytest

from opnsense_agent.config import ConfigError
from opnsense_agent.safety.diff import diff_config_xml


def test_identical_documents_have_empty_diff() -> None:
    xml = "<opnsense><system><hostname>fw</hostname></system></opnsense>"
    diff = diff_config_xml(xml, xml)
    assert diff.is_empty
    assert "No differences" in diff.render()


def test_changed_leaf_is_reported_with_old_and_new() -> None:
    a = "<opnsense><system><hostname>fw1</hostname></system></opnsense>"
    b = "<opnsense><system><hostname>fw2</hostname></system></opnsense>"
    diff = diff_config_xml(a, b)
    assert [(c.path, c.old, c.new) for c in diff.changed] == [("system/hostname", "fw1", "fw2")]
    assert not diff.added and not diff.removed


def test_added_and_removed_sections() -> None:
    a = "<opnsense><dns/></opnsense>"
    b = "<opnsense><ntp/></opnsense>"
    diff = diff_config_xml(a, b)
    assert [c.path for c in diff.removed] == ["dns"]
    assert [c.path for c in diff.added] == ["ntp"]


def test_revision_block_is_ignored() -> None:
    a = "<opnsense><revision><time>1</time></revision><x>a</x></opnsense>"
    b = "<opnsense><revision><time>2</time></revision><x>a</x></opnsense>"
    diff = diff_config_xml(a, b)
    assert diff.is_empty


def test_repeated_siblings_matched_positionally() -> None:
    a = "<opnsense><s><item><x>a</x></item><item><x>b</x></item></s></opnsense>"
    b = "<opnsense><s><item><x>a</x></item><item><x>c</x></item></s></opnsense>"
    diff = diff_config_xml(a, b)
    assert [(c.path, c.old, c.new) for c in diff.changed] == [
        ("s/item[#1]/x", "b", "c")
    ]


def test_render_summary_line_and_markers() -> None:
    a = "<opnsense><a>1</a><b>x</b></opnsense>"
    b = "<opnsense><a>2</a><c>y</c></opnsense>"
    out = diff_config_xml(a, b).render(from_label="current", to_label="backup X")
    assert out.splitlines()[0] == "Changes from current to backup X:"
    assert "  ~ a: 1 -> 2" in out
    assert "  - b" in out
    assert "  + c" in out
    assert out.splitlines()[-1] == "3 changes across 3 sections"


def test_malformed_xml_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        diff_config_xml("<not-closed>", "<opnsense/>")
```

(Delete the placeholder line in `test_changed_leaf_is_reported_with_old_and_new` — the real assertion is the `paths ==` line. It is shown only to flag that the first `assert` is illustrative; keep just the `paths`/`added`/`removed` assertions.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/safety/test_diff.py -v`
Expected: FAIL with `ModuleNotFoundError: opnsense_agent.safety.diff`.

- [ ] **Step 3: Implement `diff.py`**

Create `src/opnsense_agent/safety/diff.py`:

```python
"""Semantic diff between two OPNsense config.xml documents.

Pure, no I/O: callers pass XML text. Used by the opn_config_diff MCP tool to
show "what a restore would do" before a destructive rollback.

SECURITY: we parse with the standard library's xml.etree.ElementTree, which is
vulnerable to XML entity-expansion ("billion laughs") and external-entity
attacks on HOSTILE input. This input is our OWN firewall's config.xml — fetched
over an authenticated TLS session or read from a file we wrote — and OPNsense
config.xml carries no DTDs or entity declarations. stdlib is therefore a
deliberate, accepted v1 choice (zero new dependencies). If the trust model ever
changes (e.g. diffing configs from an untrusted source), switch to the
`defusedxml` package. See docs/superpowers/specs/2026-06-29-opn-config-diff-design.md.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element, ParseError, fromstring

from opnsense_agent.config import ConfigError

# Top-level nodes whose content always differs between any two snapshots
# (timestamps, sequence ids, change descriptions). Dropped so the diff shows
# real config deltas, not bookkeeping noise.
DEFAULT_IGNORES: frozenset[str] = frozenset({"revision"})


@dataclass(frozen=True)
class Change:
    path: str
    old: str | None  # None for additions
    new: str | None  # None for removals


@dataclass(frozen=True)
class ConfigDiff:
    added: list[Change]  # present in B only
    removed: list[Change]  # present in A only
    changed: list[Change]  # leaf text differs between A and B

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def render(self, *, from_label: str = "A", to_label: str = "B") -> str:
        if self.is_empty:
            return "No differences (revision metadata ignored)."
        lines = [f"Changes from {from_label} to {to_label}:"]
        for c in sorted(self.changed, key=lambda c: c.path):
            lines.append(f"  ~ {c.path}: {c.old} -> {c.new}")
        for c in sorted(self.removed, key=lambda c: c.path):
            lines.append(f"  - {c.path}")
        for c in sorted(self.added, key=lambda c: c.path):
            lines.append(f"  + {c.path}")
        everything = (*self.changed, *self.removed, *self.added)
        total = len(everything)
        sections = len({c.path.split("/", 1)[0] for c in everything})
        lines.append("")
        lines.append(
            f"{total} {'change' if total == 1 else 'changes'} "
            f"across {sections} {'section' if sections == 1 else 'sections'}"
        )
        return "\n".join(lines)


@dataclass
class _Acc:
    added: list[Change] = field(default_factory=list[Change])
    removed: list[Change] = field(default_factory=list[Change])
    changed: list[Change] = field(default_factory=list[Change])


def _parse(xml: str, side: str) -> Element:
    try:
        return fromstring(xml)
    except ParseError as e:
        raise ConfigError(f"failed to parse {side} config XML: {e}") from e


def _identity(child: Element, idx: int) -> str:
    """Stable identity for one of several same-tag siblings.

    Task 2: positional only. Task 3 upgrades this to uuid / identifying-child.
    """
    return f"#{idx}"


def _leaf_text(elem: Element) -> str | None:
    if len(elem):
        return None
    return (elem.text or "").strip() or None


def _key_map(
    children: list[Element], a_count: Counter[str], b_count: Counter[str]
) -> dict[tuple[str, str | None], tuple[str, Element]]:
    """Map each child to a (match-key -> (path-segment, element)) entry.

    A tag that occurs more than once on EITHER side is "multi" and gets an
    identity key/segment; otherwise the bare tag is used.
    """
    result: dict[tuple[str, str | None], tuple[str, Element]] = {}
    per_tag_index: Counter[str] = Counter()
    for child in children:
        tag = child.tag
        idx = per_tag_index[tag]
        per_tag_index[tag] += 1
        if a_count[tag] > 1 or b_count[tag] > 1:
            ident = _identity(child, idx)
            result[(tag, ident)] = (f"{tag}[{ident}]", child)
        else:
            result[(tag, None)] = (tag, child)
    return result


def _diff_pair(a: Element, b: Element, path: str, ignore: frozenset[str], acc: _Acc) -> None:
    """Compare two already-matched elements at `path`."""
    if len(a) or len(b):
        _diff_children(a, b, path, ignore, acc)
    else:
        a_text = (a.text or "").strip()
        b_text = (b.text or "").strip()
        if a_text != b_text:
            acc.changed.append(Change(path, a_text, b_text))


def _diff_children(
    a_parent: Element, b_parent: Element, path: str, ignore: frozenset[str], acc: _Acc
) -> None:
    a_children = list(a_parent)
    b_children = list(b_parent)
    a_count: Counter[str] = Counter(c.tag for c in a_children)
    b_count: Counter[str] = Counter(c.tag for c in b_children)
    a_map = _key_map(a_children, a_count, b_count)
    b_map = _key_map(b_children, a_count, b_count)

    for key, (seg, a_el) in a_map.items():
        childpath = f"{path}/{seg}" if path else seg
        if childpath in ignore:
            continue
        if key in b_map:
            _diff_pair(a_el, b_map[key][1], childpath, ignore, acc)
        else:
            acc.removed.append(Change(childpath, _leaf_text(a_el), None))

    for key, (seg, b_el) in b_map.items():
        childpath = f"{path}/{seg}" if path else seg
        if childpath in ignore:
            continue
        if key not in a_map:
            acc.added.append(Change(childpath, None, _leaf_text(b_el)))


def diff_config_xml(
    a_xml: str, b_xml: str, *, ignore_paths: frozenset[str] = DEFAULT_IGNORES
) -> ConfigDiff:
    """Diff two OPNsense config.xml documents. Reports B relative to A."""
    a = _parse(a_xml, "from")
    b = _parse(b_xml, "to")
    acc = _Acc()
    _diff_children(a, b, "", ignore_paths, acc)
    return ConfigDiff(added=acc.added, removed=acc.removed, changed=acc.changed)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/safety/test_diff.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint + type check**

Run: `.venv/bin/ruff check src/opnsense_agent/safety/diff.py tests/unit/safety/test_diff.py && .venv/bin/pyright --pythonpath .venv/bin/python src/opnsense_agent/safety/diff.py tests/unit/safety/test_diff.py`
Expected: ruff clean; pyright `0 errors`.

- [ ] **Step 6: Commit**

```bash
git add src/opnsense_agent/safety/diff.py tests/unit/safety/test_diff.py
git commit -m "$(cat <<'EOF'
feat: semantic config.xml diff core (positional keying)

Pure diff_config_xml over two config.xml strings via stdlib
ElementTree. Reports added/removed/changed with a render() that
labels direction. Repeated siblings matched positionally for now;
revision block ignored. ElementTree security tradeoff documented at
the parse site.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015gSp5YPYDcuPRh2XJqYrfp
EOF
)"
```

---

### Task 3: Smart element identity (uuid / identifying child)

**Files:**
- Modify: `src/opnsense_agent/safety/diff.py` (`_identity` + new module constant)
- Test: `tests/unit/safety/test_diff.py`

**Interfaces:**
- Consumes: `_identity(child: Element, idx: int) -> str` from Task 2.
- Produces: same signature, now keying by `uuid` attribute, then an identifying child tag, then positional. New constant `_IDENTIFYING_CHILDREN: tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/safety/test_diff.py`:

```python
def test_uuid_keyed_modify_is_change_not_add_remove_even_when_reordered() -> None:
    a = (
        "<opnsense><vlans>"
        '<vlan uuid="u1"><descr>one</descr></vlan>'
        '<vlan uuid="u2"><descr>two</descr></vlan>'
        "</vlans></opnsense>"
    )
    # Reordered AND u2's descr changed.
    b = (
        "<opnsense><vlans>"
        '<vlan uuid="u2"><descr>TWO</descr></vlan>'
        '<vlan uuid="u1"><descr>one</descr></vlan>'
        "</vlans></opnsense>"
    )
    diff = diff_config_xml(a, b)
    assert not diff.added and not diff.removed
    assert [(c.path, c.old, c.new) for c in diff.changed] == [
        ("vlans/vlan[u2]/descr", "two", "TWO")
    ]


def test_identifying_child_keying_uses_tag() -> None:
    a = (
        "<opnsense><vlans>"
        "<vlan><tag>30</tag><descr>iot</descr></vlan>"
        "<vlan><tag>40</tag><descr>cam</descr></vlan>"
        "</vlans></opnsense>"
    )
    b = (
        "<opnsense><vlans>"
        "<vlan><tag>30</tag><descr>IOT</descr></vlan>"
        "<vlan><tag>40</tag><descr>cam</descr></vlan>"
        "</vlans></opnsense>"
    )
    diff = diff_config_xml(a, b)
    assert [(c.path, c.old, c.new) for c in diff.changed] == [
        ("vlans/vlan[tag=30]/descr", "iot", "IOT")
    ]


def test_positional_fallback_when_no_identity() -> None:
    a = "<opnsense><s><item><x>a</x></item><item><x>b</x></item></s></opnsense>"
    b = "<opnsense><s><item><x>a</x></item><item><x>c</x></item></s></opnsense>"
    diff = diff_config_xml(a, b)
    assert [c.path for c in diff.changed] == ["s/item[#1]/x"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/safety/test_diff.py -v`
Expected: the two new uuid/identifying-child tests FAIL (paths show `#0`/`#1` instead of `[u2]`/`[tag=30]`); `test_positional_fallback_when_no_identity` already PASSES.

- [ ] **Step 3: Upgrade `_identity`**

In `src/opnsense_agent/safety/diff.py`, add the constant near `DEFAULT_IGNORES`:

```python
# For multiple same-tag siblings, identify each by its uuid attribute, else by
# the text of the first present child in this list, else by position. Order
# matters: STABLE identifiers first, mutable labels last. Keying on a field that
# can change (e.g. descr) would make an edit to that field look like a
# remove+add instead of an in-place change, so descr is the last resort.
_IDENTIFYING_CHILDREN: tuple[str, ...] = ("tag", "mac", "name", "if", "descr")
```

Replace `_identity` with:

```python
def _identity(child: Element, idx: int) -> str:
    """Stable identity for one of several same-tag siblings.

    Preference: uuid attribute (bare value) -> first identifying child
    ("<tag>=<value>") -> positional ("#idx"). The bare-vs-"tag=" distinction
    keeps uuid keys terse while making child-derived keys self-describing.
    """
    uuid = child.get("uuid")
    if uuid:
        return uuid
    for tag in _IDENTIFYING_CHILDREN:
        el = child.find(tag)
        if el is not None and (el.text or "").strip():
            return f"{tag}={el.text.strip()}"
    return f"#{idx}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/safety/test_diff.py -v`
Expected: all PASS (Task 2 tests still green — their inputs have no uuid/identifying children, so they stay positional).

- [ ] **Step 5: Lint + type check**

Run: `.venv/bin/ruff check src/opnsense_agent/safety/diff.py tests/unit/safety/test_diff.py && .venv/bin/pyright --pythonpath .venv/bin/python src/opnsense_agent/safety/diff.py`
Expected: ruff clean; pyright `0 errors`.

- [ ] **Step 6: Commit**

```bash
git add src/opnsense_agent/safety/diff.py tests/unit/safety/test_diff.py
git commit -m "$(cat <<'EOF'
feat: identity-based matching for repeated config.xml siblings

_identity keys same-tag siblings by uuid attribute, then an
identifying child (tag/descr/name/if/mac), then position. Reordered
model-section items now diff as in-place changes instead of
add+remove.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015gSp5YPYDcuPRh2XJqYrfp
EOF
)"
```

---

### Task 4: Wire `opn_config_diff` dispatch + README security callout

**Files:**
- Modify: `src/opnsense_agent/mcp_server.py` (add import; replace the `opn_config_diff` stub branch in `_dispatch`)
- Modify: `README.md` (ElementTree security callout under Safety guarantees)
- Test: `tests/smoke/test_mcp_server.py`

**Interfaces:**
- Consumes: `BackupStore.read_xml`, `BackupStore.fetch_current_xml` (Task 1); `diff_config_xml`, `ConfigDiff.render` (Tasks 2–3). Existing `_dispatch(name, args, *, api, ssh, backup, plan_store, pipeline, self_ip, management_if) -> Any`.
- Produces: a working `opn_config_diff` tool. No `inputSchema`/`EXPECTED_TOOLS` change ⇒ tool count stays 14.

- [ ] **Step 1: Write the failing test**

Add to `tests/smoke/test_mcp_server.py`. Its header already imports `from pathlib import Path` and `pytest`, so no top-level import changes are needed — the mock/`_dispatch`/`BackupStore` imports are local to the test below:

```python
async def test_dispatch_config_diff_vs_current(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from opnsense_agent.mcp_server import _dispatch
    from opnsense_agent.safety.backup import BackupStore

    store = BackupStore(runs_dir=tmp_path, retention=10)
    api = AsyncMock()
    # Backup snapshot: sysctl value 0.
    api.get.return_value = "<opnsense><sysctl><item><value>0</value></item></sysctl></opnsense>"
    backup_id = await store.create(api=api)
    # Live config now: sysctl value 1.
    api.get.return_value = "<opnsense><sysctl><item><value>1</value></item></sysctl></opnsense>"

    out = await _dispatch(
        "opn_config_diff",
        {"backup_id_a": backup_id},
        api=api,
        ssh=MagicMock(),
        backup=store,
        plan_store=MagicMock(),
        pipeline=MagicMock(),
        self_ip="0.0.0.0",
        management_if="igb0",
    )

    # baseline=current (value 1) -> target=backup (value 0): restoring reverts 1 -> 0.
    assert out.splitlines()[0].startswith("Changes from current to backup ")
    assert "sysctl/item/value: 1 -> 0" in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/smoke/test_mcp_server.py::test_dispatch_config_diff_vs_current -v`
Expected: FAIL — the stub returns `"config_diff: not yet implemented..."`, so the `startswith` assertion fails.

- [ ] **Step 3: Implement the dispatch branch**

In `src/opnsense_agent/mcp_server.py`, add the import in the `opnsense_agent.safety` block (immediately after the `BackupStore` import at line 36):

```python
from opnsense_agent.safety.diff import diff_config_xml
```

Replace the stub branch:

```python
    if name == "opn_config_diff":
        return "config_diff: not yet implemented in v1; track in a follow-up."
```

with:

```python
    if name == "opn_config_diff":
        # backup_id_a is the restore TARGET; baseline is backup_id_b or live config.
        # diff(baseline -> target) reads as "what restoring backup_id_a would do".
        target_id = args["backup_id_a"]
        target_xml = backup.read_xml(target_id)
        baseline_id = args.get("backup_id_b")
        if baseline_id:
            baseline_xml = backup.read_xml(baseline_id)
            from_label, to_label = f"backup {baseline_id}", f"backup {target_id}"
        else:
            baseline_xml = await backup.fetch_current_xml(api)
            from_label, to_label = "current", f"backup {target_id}"
        diff = diff_config_xml(baseline_xml, target_xml)
        return diff.render(from_label=from_label, to_label=to_label)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/smoke/test_mcp_server.py -v`
Expected: the new test PASSES; existing smoke tests (tool registration, no `opn_api_post`) still PASS.

- [ ] **Step 5: Update the README security callout**

In `README.md`, under `## Safety guarantees`, add this bullet:

```markdown
- `opn_config_diff` parses `config.xml` with the standard-library
  `xml.etree.ElementTree`. This is a deliberate zero-dependency choice: the
  input is our own firewall's config (no DTDs/entities), fetched over
  authenticated TLS or read from a file we wrote. If you ever diff configs from
  an untrusted source, switch to the hardened `defusedxml` package.
```

- [ ] **Step 6: Full gate — tests, lint, types**

Run:
```bash
.venv/bin/pytest -q && \
.venv/bin/ruff check . && .venv/bin/ruff format --check . && \
.venv/bin/pyright --pythonpath .venv/bin/python src tests
```
Expected: all tests pass (1 integration skipped); ruff clean; format clean; pyright `0 errors`.

- [ ] **Step 7: Update the graph and commit**

```bash
graphify update .
git add src/opnsense_agent/mcp_server.py tests/smoke/test_mcp_server.py README.md
git commit -m "$(cat <<'EOF'
feat: implement opn_config_diff tool

Wire the dispatch branch: read the target backup, diff it against the
baseline (another backup or the live config), render as "what restore
would do". Closes the v1 stub. README documents the ElementTree
security tradeoff.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_015gSp5YPYDcuPRh2XJqYrfp
EOF
)"
```

- [ ] **Step 8: Push and verify CI**

```bash
git push          # run with the sandbox disabled (no DNS in sandbox)
gh run watch --exit-status
```
Expected: CI green (Lint, Format, Type check, Unit + smoke tests, gitleaks).

---

## Notes for the implementer

- The `/opn-rollback` command file needs **no change** — its step-2 call
  `opn_config_diff(backup_id_a=$ARGUMENTS)` starts working the moment Task 4 lands.
- Known, accepted limitation (advisory diff): reordering an *unkeyed positional*
  list (no uuid, no identifying child) can surface as changes. Documented in the spec.
- If pre-commit reformats on commit (ruff-format collapsing lines), re-stage and
  re-commit — expected friction, not a failure.
