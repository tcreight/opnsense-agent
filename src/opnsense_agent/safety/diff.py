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

# For multiple same-tag siblings, identify each by its uuid attribute, else by
# the text of the first present child in this list, else by position. Order
# matters: STABLE identifiers first, mutable labels last. Keying on a field that
# can change (e.g. descr) would make an edit to that field look like a
# remove+add instead of an in-place change, so descr is the last resort.
_IDENTIFYING_CHILDREN: tuple[str, ...] = ("tag", "mac", "name", "if", "descr")


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

    Preference: uuid attribute (bare value) -> first identifying child
    ("<tag>=<value>") -> positional ("#idx"). The bare-vs-"tag=" distinction
    keeps uuid keys terse while making child-derived keys self-describing.
    """
    uuid = child.get("uuid")
    if uuid:
        return uuid
    for tag in _IDENTIFYING_CHILDREN:
        el = child.find(tag)
        if el is not None:
            text = (el.text or "").strip()
            if text:
                return f"{tag}={text}"
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
            # Collision guard: two siblings with no uuid and identical identifying-child
            # text (e.g. two <rule> both with <descr>web</descr>) would overwrite each
            # other in the dict, silently hiding one from the diff so a removal goes
            # unreported. Append the positional index to keep keys distinct; idx is
            # deterministic per side, so matching elements still align across A and B.
            if (tag, ident) in result:
                ident = f"{ident}#{idx}"
            result[(tag, ident)] = (f"{tag}[{ident}]", child)
        else:
            result[(tag, None)] = (tag, child)
    return result


def _diff_pair(a: Element, b: Element, path: str, ignore: frozenset[str], acc: _Acc) -> None:
    """Compare two already-matched elements at `path`."""
    # If one side is a leaf and the other has children, we recurse
    # structurally; the leaf side's text is not captured. Known, accepted
    # v1 limitation — OPNsense config.xml does not mix leaf-vs-element
    # variants of the same tag.
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
